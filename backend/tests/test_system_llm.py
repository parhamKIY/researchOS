import asyncio
import json
import os
import uuid

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_admin import admin_client as admin_client
from test_auth import PASSWORD
from test_auth import account_client as account_client

from researchos.api.admin_schemas import SystemLLMWrite, SystemProviderWrite
from researchos.api.errors import ApiError
from researchos.domain.models import (
    AuthSession,
    ModelConfiguration,
    ModelRoutingRule,
    ModelRoutingSettings,
    ProviderConnection,
    SystemLLMSettings,
    SystemProviderCandidate,
    User,
)
from researchos.providers.compatible import CompatibleProvider
from researchos.providers.contracts import ProviderFailure, TextRequest, TextResponse, TokenUsage
from researchos.services.system_llm import (
    candidate_key,
    list_system_models,
    recover_system_probes,
    settings_read,
    verify_and_apply,
)
from researchos.services.text_gateway import resolve_text_targets

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("RESEARCHOS_RUN_INTEGRATION") != "1", reason="Live PG required"),
]
KEY = "explicit-admin-fixture-key-not-live"


def apply_mock(client, headers, name="fixture-system"):
    state = client.get("/api/v1/admin/llm").json()
    response = client.post(
        "/api/v1/admin/llm/verify-and-apply",
        headers={**headers, "If-Match": state["etag"]},
        json={"adapter": "mock", "model_name": name},
    )
    assert response.status_code == 200 and response.json()["applied"], response.text
    return response.json()


def test_admin_apply_and_public_summary_keep_credentials_private(admin_client):
    client, connection, headers, regular_id = admin_client
    applied = apply_mock(client, headers)
    active_id = uuid.UUID(applied["settings"]["active"]["id"])
    assert applied["check"]["execution_mode"] == "mock"
    assert applied["check"]["total_tokens"] == 20
    assert (
        client.post(
            "/api/v1/admin/llm/verify-and-apply",
            headers=headers,
            json={"adapter": "mock", "model_name": "another"},
        ).status_code
        == 428
    )
    assert (
        client.post(
            "/api/v1/admin/llm/verify-and-apply",
            headers={**headers, "If-Match": '"1:1"'},
            json={"adapter": "mock", "model_name": "another"},
        ).status_code
        == 412
    )
    with Session(connection) as db:
        target = resolve_text_targets(db, regular_id, "paper_summary", client.app.state.settings)[0]
        assert target.source == "system" and target.configuration_id == str(active_id)
        result = asyncio.run(
            target.adapter.generate_text(
                TextRequest(model_name=target.model_name, prompt="explicit fixture"), target.key
            )
        )
        assert result.execution_mode == "mock"
        with pytest.raises(ApiError):
            resolve_text_targets(db, regular_id, "figure_analysis", client.app.state.settings)
    client.post(
        "/api/v1/auth/login",
        headers={"Origin": "http://localhost:3000"},
        json={"email": "admin-target@example.invalid", "password": PASSWORD},
    )
    assert client.get("/api/v1/admin/llm").status_code == 403
    summary = client.get("/api/v1/settings/system-model")
    assert summary.status_code == 200 and summary.json()["active"]["model_name"] == "fixture-system"
    assert "checks" not in summary.json() and "base_url" not in summary.json()["active"]
    assert "encrypted_credential" not in summary.text


def run_apply(connection, client, payload, adapter, *, match=None):
    with Session(connection, join_transaction_mode="create_savepoint") as db:
        admin = db.scalar(select(User.id).where(User.email_normalized == "account@example.invalid"))
        before = settings_read(db, admin=True)
        result = asyncio.run(
            verify_and_apply(
                db,
                admin,
                SystemLLMWrite.model_validate(payload),
                match or before["etag"],
                client.app.state.settings,
                adapters=lambda row: adapter,
            )
        )
        return json.loads(json.dumps(result, default=str))


class Success:
    async def generate_text(self, request, key):
        assert request.prompt == "Connectivity check. Reply with the word OK."
        assert request.parameters.max_output_tokens <= 256
        assert key.get_secret_value() == KEY
        return TextResponse("OK", TokenUsage(4, 1, None, 5), "live")


def test_verified_live_fixture_encrypts_key_and_only_reuses_for_same_endpoint(admin_client):
    client, connection, headers, _ = admin_client
    apply_mock(client, headers)
    body = {
        "adapter": "openai_compatible",
        "base_url": "https://api.example.com/v1",
        "model_name": "vendor/fixture",
        "api_key": KEY,
    }
    configured = run_apply(connection, client, body, Success())
    assert configured["applied"] and KEY not in json.dumps(configured, default=str)
    identifier = uuid.UUID(configured["settings"]["active"]["id"])
    with Session(connection) as db:
        candidate = db.get(SystemProviderCandidate, identifier)
        assert KEY not in candidate.encrypted_credential
        assert candidate_key(candidate, client.app.state.settings).get_secret_value() == KEY
    body.pop("api_key")
    body["model_name"] = "vendor/second"
    reused = run_apply(connection, client, body, Success())
    assert reused["applied"]
    with Session(connection) as db:
        assert db.get(SystemProviderCandidate, identifier).encrypted_credential is None
    body["base_url"] = "https://different.example.com/v1"
    with pytest.raises(ApiError) as error:
        run_apply(connection, client, body, Success())
    assert error.value.code == "credential_required"


@pytest.mark.parametrize(
    "code,unknown",
    [
        ("provider_authentication_failed", False),
        ("provider_address_rejected", False),
        ("provider_outcome_unknown", True),
        (KEY, False),
    ],
)
def test_failed_test_preserves_active_config_and_erases_candidate_key(admin_client, code, unknown):
    client, connection, headers, _ = admin_client
    before = apply_mock(client, headers)["settings"]

    class Failure:
        async def generate_text(self, request, key):
            raise ProviderFailure(code, outcome_unknown=unknown)

    result = run_apply(
        connection,
        client,
        {"adapter": "gemini", "model_name": "fixture", "api_key": KEY},
        Failure(),
    )
    assert not result["applied"]
    assert result["settings"]["active"]["id"] == before["active"]["id"]
    assert result["settings"]["revision"] == before["revision"]
    assert result["check"]["outcome_unknown"] == unknown
    assert not result["check"]["credential_configured"] and KEY not in json.dumps(
        result, default=str
    )
    with Session(connection) as db:
        assert (
            db.get(SystemProviderCandidate, uuid.UUID(result["check"]["id"])).encrypted_credential
            is None
        )


def test_concurrent_configuration_change_cannot_be_overwritten(admin_client):
    client, connection, headers, _ = admin_client
    before = apply_mock(client, headers)["settings"]

    class ChangeDuringProbe:
        async def generate_text(self, request, key):
            with Session(connection, join_transaction_mode="create_savepoint") as other:
                other.get(SystemLLMSettings, 1).revision += 1
                other.commit()
            return await Success().generate_text(request, key)

    with pytest.raises(ApiError) as error:
        run_apply(
            connection,
            client,
            {"adapter": "gemini", "model_name": "fixture", "api_key": KEY},
            ChangeDuringProbe(),
        )
    assert error.value.status_code == 412
    with Session(connection) as db:
        assert str(db.get(SystemLLMSettings, 1).active_candidate_id) == before["active"]["id"]
        latest = db.scalar(
            select(SystemProviderCandidate).where(SystemProviderCandidate.state == "stale")
        )
        assert latest and latest.encrypted_credential is None


@pytest.mark.parametrize("change", ["role", "session"])
def test_admin_authority_is_rechecked_after_network_call(admin_client, change):
    client, connection, headers, _ = admin_client
    before = apply_mock(client, headers)["settings"]
    with Session(connection) as db:
        owner = db.scalar(select(User.id).where(User.email_normalized == "account@example.invalid"))
        session_id = db.scalar(
            select(AuthSession.id).where(
                AuthSession.owner_id == owner, AuthSession.revoked_at.is_(None)
            )
        )

    class RevokeDuringProbe:
        async def generate_text(self, request, key):
            with Session(connection, join_transaction_mode="create_savepoint") as other:
                if change == "role":
                    other.get(User, owner).is_admin = False
                else:
                    from datetime import UTC, datetime

                    other.get(AuthSession, session_id).revoked_at = datetime.now(UTC)
                other.commit()
            return await Success().generate_text(request, key)

    with Session(connection, join_transaction_mode="create_savepoint") as db:
        with pytest.raises(ApiError):
            asyncio.run(
                verify_and_apply(
                    db,
                    owner,
                    SystemLLMWrite(adapter="gemini", model_name="fixture", api_key=KEY),
                    before["etag"],
                    client.app.state.settings,
                    session_id=session_id,
                    adapters=lambda row: RevokeDuringProbe(),
                )
            )
    with Session(connection) as db:
        assert str(db.get(SystemLLMSettings, 1).active_candidate_id) == before["active"]["id"]
        row = db.scalar(
            select(SystemProviderCandidate).where(
                SystemProviderCandidate.error_code == "admin_access_changed"
            )
        )
        assert row and row.encrypted_credential is None


def test_personal_route_takes_precedence_and_disabled_route_does_not_leak_to_default(admin_client):
    client, connection, headers, regular = admin_client
    apply_mock(client, headers)
    with Session(connection, join_transaction_mode="create_savepoint") as db:
        provider = ProviderConnection(
            owner_id=regular, adapter="mock", display_name="private fixture"
        )
        db.add(provider)
        db.flush()
        model = ModelConfiguration(
            owner_id=regular,
            provider_id=provider.id,
            model_name="private-model",
            capabilities=["text"],
        )
        db.add(model)
        db.flush()
        db.add(ModelRoutingSettings(owner_id=regular))
        db.flush()
        db.add(
            ModelRoutingRule(
                owner_id=regular,
                task="paper_summary",
                primary_model_id=model.id,
                allowed_provider_ids=[str(provider.id)],
            )
        )
        db.commit()
        targets = resolve_text_targets(db, regular, "paper_summary", client.app.state.settings)
        assert targets[0].source == "personal" and targets[0].model_name == "private-model"
        provider.enabled = False
        db.commit()
        with pytest.raises(ApiError):
            resolve_text_targets(db, regular, "paper_summary", client.app.state.settings)


def test_compatible_http_401_does_not_apply_or_return_provider_body(admin_client):
    client, connection, headers, _ = admin_client
    before = apply_mock(client, headers)["settings"]
    adapter = CompatibleProvider(
        "https://api.example.com/v1",
        transport=httpx.MockTransport(lambda request: httpx.Response(401, text=KEY)),
    )
    result = run_apply(
        connection,
        client,
        {
            "adapter": "openai_compatible",
            "base_url": "https://api.example.com/v1",
            "model_name": "fixture",
            "api_key": KEY,
        },
        adapter,
    )
    assert (
        not result["applied"] and result["check"]["error_code"] == "provider_authentication_failed"
    )
    assert result["settings"]["active"]["id"] == before["active"]["id"]


def test_invalid_settings_csrf_and_quota_are_checked_before_probe(admin_client):
    client, connection, headers, _ = admin_client
    current = client.get("/api/v1/admin/llm").json()
    match = {**headers, "If-Match": current["etag"]}
    route = "/api/v1/admin/llm/verify-and-apply"
    assert (
        client.post(
            route,
            json={"adapter": "mock", "model_name": "fixture"},
            headers={"Origin": "http://localhost:3000"},
        ).status_code
        == 403
    )
    for body in [
        {
            "adapter": "openai_compatible",
            "base_url": "http://127.0.0.1",
            "model_name": "fixture",
            "api_key": KEY,
        },
        {
            "adapter": "gemini",
            "base_url": "https://different.example.com",
            "model_name": "fixture",
            "api_key": KEY,
        },
        {"adapter": "mock", "model_name": "fixture", "api_key": KEY},
        {"adapter": "gemini", "model_name": "fixture", "api_key": KEY + "\n"},
        {"adapter": "gemini", "model_name": "fixture"},
    ]:
        rejected = client.post(route, headers=match, json=body)
        assert rejected.status_code == 422 and KEY not in rejected.text
    with Session(connection, join_transaction_mode="create_savepoint") as db:
        for index in range(10):
            db.add(
                SystemProviderCandidate(
                    adapter="mock",
                    model_name=f"fixture-{index}",
                    execution_mode="mock",
                    state="failed",
                )
            )
        db.commit()
    blocked = client.post(route, headers=match, json={"adapter": "mock", "model_name": "fixture"})
    assert blocked.status_code == 429 and blocked.headers["retry-after"] == "60"


def test_network_timeout_never_applies_or_retries(admin_client):
    client, connection, headers, _ = admin_client
    before = apply_mock(client, headers)["settings"]

    class Timeout:
        calls = 0

        async def generate_text(self, request, key):
            self.calls += 1
            raise TimeoutError("private fixture")

    adapter = Timeout()
    result = run_apply(
        connection, client, {"adapter": "gemini", "model_name": "fixture", "api_key": KEY}, adapter
    )
    assert not result["applied"] and result["check"]["outcome_unknown"] and adapter.calls == 1
    assert result["settings"]["active"]["id"] == before["active"]["id"]


def test_abandoned_probe_cleanup_preserves_active_and_recent_probe(admin_client):
    from datetime import UTC, datetime, timedelta

    client, connection, headers, _ = admin_client
    before = apply_mock(client, headers)["settings"]
    with Session(connection, join_transaction_mode="create_savepoint") as db:
        abandoned = SystemProviderCandidate(
            adapter="gemini",
            model_name="fixture",
            execution_mode="live",
            encrypted_credential="explicit-encrypted-fixture",
            created_at=datetime.now(UTC) - timedelta(minutes=6),
        )
        recent = SystemProviderCandidate(
            adapter="gemini",
            model_name="recent",
            execution_mode="live",
            encrypted_credential="explicit-encrypted-fixture",
        )
        db.add_all([abandoned, recent])
        db.commit()
        assert recover_system_probes(db) == 1
        assert (
            abandoned.state == "failed"
            and abandoned.outcome_unknown
            and abandoned.encrypted_credential is None
        )
        assert recent.state == "testing" and recent.encrypted_credential
        current = db.get(SystemLLMSettings, 1)
        assert (
            str(current.active_candidate_id) == before["active"]["id"]
            and current.revision == before["revision"]
        )


def test_model_discovery_requires_admin_csrf_and_never_activates(admin_client):
    client, _, headers, _ = admin_client
    before = apply_mock(client, headers)["settings"]
    route = "/api/v1/admin/llm/models"
    assert client.post(route, json={"adapter": "mock"}).status_code == 403
    result = client.post(route, headers=headers, json={"adapter": "mock"})
    assert result.status_code == 200 and result.json()["execution_mode"] == "mock"
    assert client.get("/api/v1/admin/llm").json() == before
    # Blank credentials must never be sent to another endpoint.
    assert client.post(route, headers=headers, json={"adapter": "gemini"}).status_code == 422
    for _ in range(8):
        assert client.post(route, headers=headers, json={"adapter": "mock"}).status_code == 200
    limited = client.post(route, headers=headers, json={"adapter": "mock"})
    assert limited.status_code == 429 and limited.headers["Retry-After"] == "60"
    login = client.post(
        "/api/v1/auth/login",
        headers={"Origin": "http://localhost:3000"},
        json={"email": "admin-target@example.invalid", "password": PASSWORD},
    )
    assert (
        client.post(
            route,
            headers={**headers, "X-CSRF-Token": login.json()["csrf_token"]},
            json={"adapter": "mock"},
        ).status_code
        == 403
    )


def test_catalog_reuses_encrypted_key_without_persisting_discovery(admin_client):
    client, connection, _, _ = admin_client
    body = {"adapter": "gemini", "model_name": "fixture", "api_key": KEY}
    before = run_apply(connection, client, body, Success())["settings"]

    async def catalog(adapter, base, key):
        assert adapter == "gemini" and key.get_secret_value() == KEY
        return {"items": [{"id": "fixture", "display_name": "Fixture"}], "execution_mode": "live"}

    with Session(connection, join_transaction_mode="create_savepoint") as db:
        owner = db.scalar(select(User.id).where(User.email_normalized == "account@example.invalid"))
        count = len(list(db.scalars(select(SystemProviderCandidate))))
        result = asyncio.run(
            list_system_models(
                db,
                owner,
                SystemProviderWrite(adapter="gemini"),
                client.app.state.settings,
                discover=catalog,
            )
        )
        assert result["items"][0]["id"] == "fixture" and KEY not in json.dumps(result)
        assert len(list(db.scalars(select(SystemProviderCandidate)))) == count
        assert json.loads(json.dumps(settings_read(db, admin=True), default=str)) == before


@pytest.mark.parametrize("revoke", [False, True])
def test_catalog_sanitizes_failures_and_rechecks_authority(admin_client, revoke):
    client, connection, _, _ = admin_client

    async def catalog(adapter, base, key):
        if not revoke:
            raise ProviderFailure(KEY)
        with Session(connection, join_transaction_mode="create_savepoint") as db:
            db.scalar(
                select(User).where(User.email_normalized == "account@example.invalid")
            ).is_admin = False
            db.commit()
        return {"items": [], "execution_mode": "live"}

    with Session(connection, join_transaction_mode="create_savepoint") as db:
        owner = db.scalar(select(User.id).where(User.email_normalized == "account@example.invalid"))
        with pytest.raises(ApiError) as error:
            asyncio.run(
                list_system_models(
                    db,
                    owner,
                    SystemProviderWrite(adapter="gemini", api_key=KEY),
                    client.app.state.settings,
                    discover=catalog,
                )
            )
        assert error.value.status_code == (403 if revoke else 502)
        assert KEY not in str(error.value.detail)
