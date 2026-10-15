import json
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_analysis import analysis_fixture as analysis_fixture
from test_analysis import enqueue, prepared
from test_auth import account_client as account_client

from researchos.domain.models import AnalysisAttempt, AnalysisReport, ModelConfiguration
from researchos.providers.contracts import ProviderFailure, TextResponse
from researchos.providers.mock import MockProvider
from researchos.services.analysis_worker import (
    dispatch_analyses,
    execute_analysis,
    recover_analyses,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("RESEARCHOS_RUN_INTEGRATION") != "1", reason="Live PG required"),
]


def execute(fixture, identifier, adapter=None):
    client, connection, _, _ = fixture
    return execute_analysis(
        uuid.UUID(identifier),
        client.app.state.settings,
        lambda: Session(connection, join_transaction_mode="create_savepoint"),
        adapter_override=adapter,
    )


@pytest.mark.parametrize("language", ["fa", "en"])
def test_complete_mock_report_exact_evidence_history_and_duplicate_delivery(
    analysis_fixture, language
):
    client, _, _, (_, paper, _, _, _) = analysis_fixture
    response = enqueue(analysis_fixture, prepared(analysis_fixture, language))
    identifier = response.json()["id"]
    assert execute(analysis_fixture, identifier)["status"] == "completed"
    assert execute(analysis_fixture, identifier)["status"] == "ignored"
    result = client.get(f"/api/v1/analyses/{identifier}").json()
    assert len(result["sections"]) == 7 and result["progress"] == 100
    assert len(result["usage"]) == 7 and all(
        row["execution_mode"] == "mock" for row in result["usage"]
    )
    assert result["scientific_verification"] == "not_evaluated"
    for section in result["sections"]:
        assert section["state"] in {"completed", "unavailable"}
        for claim in section["payload"]["items"]:
            assert ("آزمایشی" in claim["text"]) if language == "fa" else "MOCK" in claim["text"]
            witness = claim["evidence"][0]
            page = client.get(
                f"/api/v1/document-versions/{result['document_version_id']}/pages/{witness['page_number']}"
            ).json()
            assert page["text"][witness["start_offset"] : witness["end_offset"]] == witness["quote"]
    assert client.get(f"/api/v1/papers/{paper}/analyses").json()["items"][0]["id"] == identifier


def test_bad_citation_fails_only_that_section_and_never_publishes_invalid_claim(analysis_fixture):
    class InvalidCitation:
        async def generate_text(self, request, key):
            result = await MockProvider().generate_text(request, key)
            payload = json.loads(result.text)
            payload["items"][0]["evidence"][0]["quote"] = "invented quote"
            return TextResponse(json.dumps(payload), result.usage, "mock")

    identifier = enqueue(analysis_fixture).json()["id"]
    result = execute(
        analysis_fixture,
        identifier,
        lambda target, section, index: (
            InvalidCitation() if section == "methodology" else MockProvider()
        ),
    )
    assert result["status"] == "partially_completed"
    detail = analysis_fixture[0].get(f"/api/v1/analyses/{identifier}").json()
    failed = next(part for part in detail["sections"] if part["kind"] == "methodology")
    assert failed["payload"] is None and failed["error_code"] == "analysis_output_invalid"
    assert "invented quote" not in json.dumps(detail)


def test_ambiguous_timeout_stops_without_retry_and_records_possible_usage(analysis_fixture):
    class Failure:
        calls = 0

        async def generate_text(self, request, key):
            self.calls += 1
            raise ProviderFailure("provider_outcome_unknown", outcome_unknown=True)

    adapter = Failure()
    identifier = enqueue(analysis_fixture).json()["id"]
    assert execute(analysis_fixture, identifier, lambda *args: adapter)["status"] == "failed"
    detail = analysis_fixture[0].get(f"/api/v1/analyses/{identifier}").json()
    assert detail["outcome_unknown"] and len(detail["usage"]) == adapter.calls == 1
    assert detail["usage"][0]["state"] == "outcome_unknown"
    assert detail["usage"][0]["total_tokens"] is None


def test_changed_configuration_prevents_any_call(analysis_fixture):
    client, connection, _, (_, _, _, model, _) = analysis_fixture
    identifier = enqueue(analysis_fixture).json()["id"]
    with Session(connection, join_transaction_mode="create_savepoint") as db:
        db.get(ModelConfiguration, model).revision += 1
        db.commit()

    def forbidden(*args):
        pytest.fail("A provider must not be called after configuration changes")

    assert execute(analysis_fixture, identifier, forbidden)["status"] == "failed"
    assert not client.get(f"/api/v1/analyses/{identifier}").json()["usage"]


def test_disabled_user_cannot_start_a_queued_provider_call(analysis_fixture):
    from researchos.domain.models import User

    _, connection, _, (owner, _, _, _, _) = analysis_fixture
    identifier = enqueue(analysis_fixture).json()["id"]
    with Session(connection, join_transaction_mode="create_savepoint") as db:
        db.get(User, owner).is_active = False
        db.commit()

    def forbidden(*args):
        pytest.fail("Disabled owner must not call a provider")

    assert execute(analysis_fixture, identifier, forbidden)["status"] == "failed"


def test_dispatch_recovery_never_replays_a_started_paid_request(analysis_fixture):
    _, connection, _, (owner, _, _, model, _) = analysis_fixture
    identifier = uuid.UUID(enqueue(analysis_fixture).json()["id"])

    class Publisher:
        def send_task(self, *args, **kwargs):
            raise OSError("explicit fixture broker outage")

    with Session(connection, join_transaction_mode="create_savepoint") as db:
        assert dispatch_analyses(db, Publisher()) == 0
        report = db.get(AnalysisReport, identifier)
        assert report.state == "queued"
        report.state, report.lease_token = "running", uuid.uuid4()
        report.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.add(
            AnalysisAttempt(
                owner_id=owner,
                report_id=identifier,
                section="overview",
                configuration_id=model,
                model_name="explicit fixture",
                execution_mode="mock",
                state="started",
            )
        )
        db.commit()
        assert recover_analyses(db) == 1
        assert db.get(AnalysisReport, identifier).state == "failed"
        assert db.get(AnalysisReport, identifier).outcome_unknown
        assert (
            db.scalar(select(AnalysisAttempt.state).where(AnalysisAttempt.report_id == identifier))
            == "outcome_unknown"
        )
    assert execute(analysis_fixture, str(identifier))["status"] == "ignored"


def test_delete_rejected_while_report_is_active(analysis_fixture):
    client, _, headers, (_, paper, _, _, _) = analysis_fixture
    enqueue(analysis_fixture)
    current = client.get(f"/api/v1/papers/{paper}")
    assert (
        client.delete(
            f"/api/v1/papers/{paper}", headers={**headers, "If-Match": current.headers["etag"]}
        ).status_code
        == 409
    )


@pytest.mark.parametrize("unknown", [False, True])
def test_fallback_requires_approved_route_and_never_replays_uncertain_outcome(
    analysis_fixture, unknown
):
    from researchos.domain.models import ModelRoutingRule

    client, connection, _, (owner, _, _, primary, provider) = analysis_fixture
    with Session(connection, join_transaction_mode="create_savepoint") as db:
        fallback = ModelConfiguration(
            owner_id=owner,
            provider_id=provider,
            model_name="explicit-fallback",
            capabilities=["text"],
        )
        db.add(fallback)
        db.flush()
        for rule in db.scalars(select(ModelRoutingRule).where(ModelRoutingRule.owner_id == owner)):
            rule.fallback_model_id = fallback.id
        db.commit()

    class Failure:
        async def generate_text(self, request, key):
            raise ProviderFailure(
                "provider_outcome_unknown" if unknown else "provider_authentication_failed",
                outcome_unknown=unknown,
            )

    identifier = enqueue(analysis_fixture).json()["id"]
    result = execute(
        analysis_fixture,
        identifier,
        lambda target, section, index: MockProvider() if index else Failure(),
    )
    assert result["status"] == ("failed" if unknown else "completed")
    usage = client.get(f"/api/v1/analyses/{identifier}").json()["usage"]
    assert len(usage) == (1 if unknown else 14)


def test_queued_privacy_revocation_prevents_outbound_request(analysis_fixture):
    from researchos.core.credentials import CredentialCipher
    from researchos.domain.models import Paper, ProviderConnection

    client, connection, _, (owner, paper_id, _, _, provider_id) = analysis_fixture
    with Session(connection, join_transaction_mode="create_savepoint") as db:
        provider = db.get(ProviderConnection, provider_id)
        provider.adapter = "gemini"
        provider.encrypted_credential = CredentialCipher(
            client.app.state.settings.credential_encryption_key.get_secret_value()
        ).encrypt("explicit-fixture-not-live", owner, provider_id)
        db.get(Paper, paper_id).external_processing_allowed = True
        db.commit()
    body = {**prepared(analysis_fixture), "acknowledge_external_processing": True}
    identifier = enqueue(analysis_fixture, body).json()["id"]
    with Session(connection, join_transaction_mode="create_savepoint") as db:
        db.get(Paper, paper_id).external_processing_allowed = False
        db.commit()

    def forbidden(*args):
        pytest.fail("Revoked privacy must prevent provider execution")

    assert execute(analysis_fixture, identifier, forbidden)["status"] == "failed"
    assert client.get(f"/api/v1/analyses/{identifier}").json()["usage"] == []
