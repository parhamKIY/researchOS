import asyncio
import os
import uuid

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_auth import ORIGIN, sign_in
from test_auth import account_client as account_client

from researchos.cli import provision_user
from researchos.core.credentials import CredentialCipher
from researchos.domain.models import AIUsageRecord, ProviderConnection, User
from researchos.providers.contracts import ProviderFailure
from researchos.providers.gemini import GeminiProvider
from researchos.services.provider_testing import test_connection as run_connection_test
from researchos.services.providers import resolve_route

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("RESEARCHOS_RUN_INTEGRATION") != "1", reason="Live PG required"),
]
KEY = "explicit-integration-fixture-key-not-live"


@pytest.fixture
def providers(account_client):
    client, connection = account_client
    response = sign_in(client)
    headers = {**ORIGIN, "X-CSRF-Token": response.json()["csrf_token"]}
    return client, connection, headers


def add(client, headers, adapter="mock"):
    body = {"adapter": adapter, "display_name": "Explicit integration fixture"}
    if adapter == "gemini":
        body["api_key"] = KEY
    result = client.post("/api/v1/providers", headers=headers, json=body)
    assert result.status_code == 201, result.text
    return result


def model(client, headers, provider, name="fixture-model", capabilities=None):
    result = client.post(
        f"/api/v1/providers/{provider}/models",
        headers=headers,
        json={
            "model_name": name,
            "capabilities": capabilities or ["text"],
            "parameters": {"temperature": 0.3},
        },
    )
    assert result.status_code == 201, result.text
    return result


def test_credential_replacement_clear_and_soft_delete_never_echo_key(providers):
    client, connection, headers = providers
    response = add(client, headers, "gemini")
    provider_id = response.json()["id"]
    route = f"/api/v1/providers/{provider_id}"
    assert KEY not in response.text and response.json()["credential_configured"]
    assert "encrypted_credential" not in response.json()
    with Session(connection) as db:
        record = db.get(ProviderConnection, uuid.UUID(provider_id))
        assert KEY not in record.encrypted_credential
        cipher = CredentialCipher(
            client.app.state.settings.credential_encryption_key.get_secret_value()
        )
        assert cipher.decrypt(record.encrypted_credential, record.owner_id, record.id) == KEY
    assert client.patch(route, headers=headers, json={"enabled": False}).status_code == 428
    replacement = KEY + "-replacement"
    changed = client.patch(
        route,
        headers={**headers, "If-Match": response.headers["etag"]},
        json={"api_key": replacement},
    )
    assert changed.status_code == 200 and replacement not in changed.text
    assert (
        client.patch(
            route,
            headers={**headers, "If-Match": response.headers["etag"]},
            json={"enabled": False},
        ).status_code
        == 412
    )
    cleared = client.patch(
        route,
        headers={**headers, "If-Match": changed.headers["etag"]},
        json={"clear_credential": True},
    )
    assert cleared.status_code == 200 and not cleared.json()["credential_configured"]
    assert (
        client.delete(route, headers={**headers, "If-Match": cleared.headers["etag"]}).status_code
        == 204
    )
    assert client.get(route).status_code == 404
    with Session(connection) as db:
        record = db.get(ProviderConnection, uuid.UUID(provider_id))
        assert record.encrypted_credential is None and not record.enabled and record.deleted_at


def test_mock_connectivity_usage_and_runtime_routing_validation(providers):
    client, connection, headers = providers
    provider = add(client, headers).json()["id"]
    first = model(client, headers, provider)
    first_id = first.json()["id"]
    second = model(client, headers, provider, "another-fixture").json()["id"]
    assert first.json()["capability_source"] == "manual"
    probe = client.post(
        f"/api/v1/providers/{provider}/test",
        headers=headers,
        json={"model_configuration_id": first_id},
    )
    assert (
        probe.status_code == 200
        and probe.json()["execution_mode"] == "mock"
        and probe.json()["code"] == "mock_connection_ok"
    )
    usage = client.get("/api/v1/analytics/usage").json()["items"][0]
    assert usage["total_tokens"] == 20 and usage["cost_source"] == "mock_no_charge"
    assert "prompt" not in usage and "owner_id" not in usage
    routing = client.get("/api/v1/settings/model-routing")
    payload = {
        "rules": [
            {
                "task": "paper_summary",
                "primary_model_id": first_id,
                "fallback_model_id": second,
                "allowed_provider_ids": [provider],
            }
        ]
    }
    saved = client.put(
        "/api/v1/settings/model-routing",
        headers={**headers, "If-Match": routing.headers["etag"]},
        json=payload,
    )
    assert saved.status_code == 200, saved.text
    with Session(connection) as db:
        owner = db.scalar(select(User.id).where(User.email_normalized == "account@example.invalid"))
        assert resolve_route(db, owner, "paper_summary")[0][0].id == uuid.UUID(first_id)
    bad = {
        "rules": [
            {
                "task": "figure_analysis",
                "primary_model_id": first_id,
                "allowed_provider_ids": [provider],
            }
        ]
    }
    assert (
        client.put(
            "/api/v1/settings/model-routing",
            headers={**headers, "If-Match": saved.headers["etag"]},
            json=bad,
        ).status_code
        == 422
    )
    assert client.get("/api/v1/settings/model-routing").json()["rules"] == saved.json()["rules"]
    assert (
        client.put(
            "/api/v1/settings/model-routing",
            headers={**headers, "If-Match": routing.headers["etag"]},
            json=payload,
        ).status_code
        == 412
    )
    disabled = client.patch(
        f"/api/v1/models/{first_id}",
        headers={**headers, "If-Match": first.headers["etag"]},
        json={"enabled": False},
    )
    assert disabled.status_code == 200
    assert (
        client.post(
            f"/api/v1/providers/{provider}/test",
            headers=headers,
            json={"model_configuration_id": first_id},
        ).status_code
        == 409
    )


def test_private_provider_model_and_usage_routes_reject_foreign_ids(providers):
    client, _, headers = providers
    provider = add(client, headers).json()["id"]
    configured = model(client, headers, provider).json()["id"]
    for route in [
        f"/api/v1/providers/{uuid.uuid4()}",
        f"/api/v1/models/{uuid.uuid4()}",
    ]:
        assert client.get(route).status_code == 404
    assert (
        client.post(
            f"/api/v1/providers/{provider}/test",
            headers=ORIGIN,
            json={"model_configuration_id": configured},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/providers",
            headers=headers,
            json={
                "adapter": "gemini",
                "display_name": "fixture",
                "api_key": KEY,
                "base_url": "http://127.0.0.1",
            },
        ).status_code
        == 422
    )


def test_other_account_cannot_read_change_or_test_private_provider(providers):
    client, connection, headers = providers
    response = add(client, headers, "gemini")
    provider = response.json()["id"]
    configured = model(client, headers, provider).json()["id"]
    with Session(connection, join_transaction_mode="create_savepoint") as db:
        provision_user(
            db, "other-provider-fixture@example.invalid", "other disposable fixture password"
        )
        db.commit()
    login = client.post(
        "/api/v1/auth/login",
        headers=ORIGIN,
        json={
            "email": "other-provider-fixture@example.invalid",
            "password": "other disposable fixture password",
        },
    )
    other_headers = {**ORIGIN, "X-CSRF-Token": login.json()["csrf_token"]}
    for route in [
        f"/api/v1/providers/{provider}",
        f"/api/v1/providers/{provider}/models",
        f"/api/v1/models/{configured}",
    ]:
        assert client.get(route).status_code == 404
    assert (
        client.patch(
            f"/api/v1/providers/{provider}",
            headers={**other_headers, "If-Match": response.headers["etag"]},
            json={"enabled": False},
        ).status_code
        == 404
    )
    assert client.delete(f"/api/v1/providers/{provider}", headers=other_headers).status_code == 404
    assert (
        client.post(
            f"/api/v1/providers/{provider}/test",
            headers=other_headers,
            json={"model_configuration_id": configured},
        ).status_code
        == 404
    )
    assert client.get("/api/v1/analytics/usage").json()["items"] == []
    assert (
        client.post(
            f"/api/v1/providers/{provider}/models",
            headers=other_headers,
            json={
                "model_name": "other",
                "capabilities": ["text"],
                "capability_source": "provider_verified",
            },
        ).status_code
        == 422
    )


def test_ambiguous_network_failure_is_not_retried_and_cost_stays_unknown(providers):
    client, connection, headers = providers
    provider = add(client, headers, "gemini").json()["id"]
    configured = model(client, headers, provider).json()["id"]
    calls = []

    def server(request):
        calls.append(request)
        raise httpx.ReadTimeout("Deliberate fixture containing private input")

    with Session(connection, join_transaction_mode="create_savepoint") as db:
        owner = db.scalar(select(User.id).where(User.email_normalized == "account@example.invalid"))
        result = asyncio.run(
            run_connection_test(
                db,
                owner,
                uuid.UUID(provider),
                uuid.UUID(configured),
                client.app.state.settings,
                adapters=lambda _: GeminiProvider(httpx.MockTransport(server)),
            )
        )
        assert (
            result["outcome_unknown"]
            and result["code"] == "provider_outcome_unknown"
            and len(calls) == 1
        )
        row = db.scalar(select(AIUsageRecord).where(AIUsageRecord.owner_id == owner))
        assert (
            row.state == "outcome_unknown" and row.cost_amount is None and row.total_tokens is None
        )


def test_explicit_rate_limit_is_retried_once_and_recorded_per_attempt(providers):
    client, connection, headers = providers
    provider = add(client, headers).json()["id"]
    configured = model(client, headers, provider).json()["id"]

    class OfflineFixture:
        async def generate_text(self, request, key):
            raise ProviderFailure("provider_rate_limited", retryable=True)

    with Session(connection, join_transaction_mode="create_savepoint") as db:
        owner = db.scalar(select(User.id).where(User.email_normalized == "account@example.invalid"))
        result = asyncio.run(
            run_connection_test(
                db,
                owner,
                uuid.UUID(provider),
                uuid.UUID(configured),
                client.app.state.settings,
                adapters=lambda _: OfflineFixture(),
            )
        )
        assert len(result["usage_ids"]) == 2
        assert (
            len(list(db.scalars(select(AIUsageRecord).where(AIUsageRecord.owner_id == owner)))) == 2
        )
