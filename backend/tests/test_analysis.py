import os
import uuid

import pytest
from sqlalchemy.orm import Session
from test_auth import ORIGIN, PASSWORD, sign_in
from test_auth import account_client as account_client

from researchos.cli import provision_user
from researchos.core.credentials import CredentialCipher
from researchos.domain.models import (
    AnalysisReport,
    DocumentPage,
    DocumentVersion,
    ModelConfiguration,
    ModelRoutingRule,
    ModelRoutingSettings,
    Paper,
    PaperFile,
    ProviderConnection,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("RESEARCHOS_RUN_INTEGRATION") != "1", reason="Live PG required"),
]


@pytest.fixture
def analysis_fixture(account_client):
    client, connection = account_client
    login = sign_in(client)
    headers = {**ORIGIN, "X-CSRF-Token": login.json()["csrf_token"]}
    with Session(connection, join_transaction_mode="create_savepoint") as db:
        owner = uuid.UUID(login.json()["user"]["id"])
        paper = Paper(owner_id=owner, title="Explicit synthetic analysis fixture")
        db.add(paper)
        db.flush()
        file = PaperFile(
            owner_id=owner,
            paper_id=paper.id,
            sha256="b" * 64,
            storage_key=f"{uuid.uuid4().hex}.pdf",
            original_name="fixture.pdf",
            byte_size=100,
        )
        db.add(file)
        db.flush()
        version = DocumentVersion(
            owner_id=owner,
            paper_id=paper.id,
            file_id=file.id,
            state="ready",
            parser_name="explicit-test-fixture",
            parser_version="1",
            parser_config={},
        )
        db.add(version)
        db.flush()
        db.add(
            DocumentPage(
                owner_id=owner,
                document_version_id=version.id,
                page_number=1,
                text="Synthetic 😀 source. Accuracy 90% on DATA. Not a real research finding.",
                text_status="available",
                width=400,
                height=600,
            )
        )
        provider = ProviderConnection(
            owner_id=owner, adapter="mock", display_name="Explicit fixture"
        )
        db.add(provider)
        db.flush()
        model = ModelConfiguration(
            owner_id=owner,
            provider_id=provider.id,
            model_name="analysis-fixture",
            capabilities=["text"],
        )
        db.add(model)
        db.flush()
        db.add(ModelRoutingSettings(owner_id=owner))
        db.flush()
        for task in ["paper_summary", "methodology", "research_gaps"]:
            db.add(
                ModelRoutingRule(
                    owner_id=owner,
                    task=task,
                    primary_model_id=model.id,
                    allowed_provider_ids=[str(provider.id)],
                )
            )
        ids = (owner, paper.id, version.id, model.id, provider.id)
        db.commit()
    return client, connection, headers, ids


def prepared(fixture, language="en"):
    client, _, _, (_, paper, version, _, _) = fixture
    response = client.get(
        f"/api/v1/papers/{paper}/analysis-plan",
        params={"document_version_id": str(version), "language": language},
    )
    assert response.status_code == 200, response.text
    plan = response.json()
    return {
        "document_version_id": str(version),
        "language": language,
        "plan_fingerprint": plan["fingerprint"],
        "approved_configuration_ids": [row["configuration_id"] for row in plan["targets"]],
    }


def enqueue(fixture, body=None, key="fixture-analysis"):
    client, _, headers, (_, paper, _, _, _) = fixture
    return client.post(
        f"/api/v1/papers/{paper}/analyses",
        headers={**headers, "Idempotency-Key": key},
        json=body or prepared(fixture),
    )


def test_enqueue_replay_configuration_guard_and_active_conflict(analysis_fixture):
    client, connection, headers, (owner, paper, _, model_id, _) = analysis_fixture
    body = prepared(analysis_fixture)
    assert (
        client.post(f"/api/v1/papers/{paper}/analyses", headers=ORIGIN, json=body).status_code
        == 403
    )
    response = enqueue(analysis_fixture, body)
    assert response.status_code == 202 and response.headers["location"].startswith(
        "/api/v1/analyses/"
    )
    identifier = response.json()["id"]
    assert enqueue(analysis_fixture, body).json() == response.json()
    assert enqueue(analysis_fixture, body, "another-key").status_code == 409
    assert enqueue(analysis_fixture, {**body, "language": "fa"}).status_code == 409
    detail = client.get(f"/api/v1/analyses/{identifier}")
    assert detail.status_code == 200 and detail.json()["state"] == "queued"
    assert "key" not in str(detail.json()["configuration"]["routes"])
    assert client.get(f"/api/v1/papers/{paper}/analyses").json()["items"][0]["id"] == identifier
    with Session(connection, join_transaction_mode="create_savepoint") as db:
        db.get(AnalysisReport, uuid.UUID(identifier)).state = "failed"
        db.get(ModelConfiguration, model_id).revision += 1
        db.commit()
    assert enqueue(analysis_fixture, body, "stale-key").status_code == 412


def test_consent_is_exact_and_private_documents_cannot_be_sent(analysis_fixture):
    client, connection, _, (_, _, _, _, provider_id) = analysis_fixture
    body = prepared(analysis_fixture)
    assert (
        enqueue(
            analysis_fixture, {**body, "approved_configuration_ids": [str(uuid.uuid4())]}
        ).status_code
        == 422
    )
    with Session(connection, join_transaction_mode="create_savepoint") as db:
        provider = db.get(ProviderConnection, provider_id)
        provider.adapter = "gemini"
        provider.encrypted_credential = CredentialCipher(
            client.app.state.settings.credential_encryption_key.get_secret_value()
        ).encrypt("explicit-fixture-not-live", provider.owner_id, provider.id)
        db.commit()
    blocked = client.get(
        f"/api/v1/papers/{analysis_fixture[3][1]}/analysis-plan",
        params={"document_version_id": str(analysis_fixture[3][2])},
    )
    assert blocked.status_code == 200 and blocked.json()["external_required"]
    assert (
        enqueue(analysis_fixture, prepared(analysis_fixture), "private-denied").status_code == 403
    )


def test_foreign_version_report_history_and_unknown_retry_requirements(analysis_fixture):
    client, connection, _, (owner, paper, _, _, _) = analysis_fixture
    body = prepared(analysis_fixture)
    assert (
        enqueue(analysis_fixture, {**body, "document_version_id": str(uuid.uuid4())}).status_code
        == 404
    )
    response = enqueue(analysis_fixture)
    report_id = uuid.UUID(response.json()["id"])
    with Session(connection, join_transaction_mode="create_savepoint") as db:
        report = db.get(AnalysisReport, report_id)
        report.state, report.outcome_unknown = "failed", True
        provision_user(db, "analysis-stranger@example.invalid", PASSWORD)
        db.commit()
    retry = {**prepared(analysis_fixture), "retry_of_id": str(report_id)}
    assert enqueue(analysis_fixture, retry, "retry-no-ack").status_code == 409
    assert (
        enqueue(
            analysis_fixture, {**retry, "acknowledge_unknown_outcome": True}, "retry-with-ack"
        ).status_code
        == 202
    )
    client.post(
        "/api/v1/auth/login",
        headers=ORIGIN,
        json={"email": "analysis-stranger@example.invalid", "password": PASSWORD},
    )
    assert client.get(f"/api/v1/analyses/{report_id}").status_code == 404
    assert client.get(f"/api/v1/papers/{paper}/analyses").status_code == 404
    assert (
        client.get(
            f"/api/v1/papers/{paper}/analysis-plan",
            params={"document_version_id": body["document_version_id"]},
        ).status_code
        == 404
    )
