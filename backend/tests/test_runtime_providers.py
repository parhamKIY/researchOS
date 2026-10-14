import os
import uuid

import httpx
import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from researchos.cli import provision_user
from researchos.core.config import Settings
from researchos.domain.models import ProviderConnection, User
from researchos.infrastructure.database import build_engine

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RESEARCHOS_RUN_INTEGRATION") != "1", reason="Live stack required"
    ),
]


def test_live_provider_settings_proxy_encryption_mock_usage_and_dynamic_routes():
    settings = Settings()
    engine = build_engine(settings)
    email = f"provider-runtime-{uuid.uuid4().hex}@example.invalid"
    password = "Disposable provider runtime fixture password"
    secret = f"fake-provider-fixture-{uuid.uuid4().hex}"
    with Session(engine) as db:
        owner = provision_user(db, email, password).id
        db.commit()
    try:
        with httpx.Client(base_url="http://frontend:3000", timeout=30) as client:
            origin = {"Origin": str(settings.public_origin).rstrip("/")}
            signed_in = client.post(
                "/api/v1/auth/login", headers=origin, json={"email": email, "password": password}
            )
            assert signed_in.status_code == 200
            headers = {**origin, "X-CSRF-Token": signed_in.json()["csrf_token"]}
            real = client.post(
                "/api/v1/providers",
                headers=headers,
                json={
                    "adapter": "gemini",
                    "display_name": "Fake-key storage fixture; not a live test",
                    "api_key": secret,
                },
            )
            assert real.status_code == 201 and secret not in real.text
            with Session(engine) as db:
                stored = db.get(ProviderConnection, uuid.UUID(real.json()["id"]))
                assert stored.encrypted_credential and secret not in stored.encrypted_credential
            mock = client.post(
                "/api/v1/providers",
                headers=headers,
                json={"adapter": "mock", "display_name": "Explicit runtime mock"},
            )
            provider = mock.json()["id"]
            configured = client.post(
                f"/api/v1/providers/{provider}/models",
                headers=headers,
                json={
                    "model_name": "runtime-fixture",
                    "capabilities": ["text"],
                    "parameters": {"temperature": 0.2},
                },
            )
            assert configured.status_code == 201
            model_id = configured.json()["id"]
            probe = client.post(
                f"/api/v1/providers/{provider}/test",
                headers=headers,
                json={"model_configuration_id": model_id},
            )
            assert (
                probe.status_code == 200
                and probe.json()["status"] == "ok"
                and probe.json()["execution_mode"] == "mock"
            )
            routing = client.get("/api/v1/settings/model-routing")
            rule = {
                "task": "paper_summary",
                "primary_model_id": model_id,
                "allowed_provider_ids": [provider],
            }
            saved = client.put(
                "/api/v1/settings/model-routing",
                headers={**headers, "If-Match": routing.headers["etag"]},
                json={"rules": [rule]},
            )
            assert saved.status_code == 200
            changed = client.patch(
                f"/api/v1/models/{model_id}",
                headers={**headers, "If-Match": configured.headers["etag"]},
                json={"model_name": "changed-runtime-fixture", "parameters": {"temperature": 0.7}},
            )
            assert changed.status_code == 200
            assert (
                client.post(
                    f"/api/v1/providers/{provider}/test",
                    headers=headers,
                    json={"model_configuration_id": model_id},
                ).json()["status"]
                == "ok"
            )
            history = client.get("/api/v1/analytics/usage").json()["items"]
            assert {item["model_name"] for item in history} == {
                "runtime-fixture",
                "changed-runtime-fixture",
            }
            with httpx.Client(
                base_url="http://frontend:3000", cookies=client.cookies, timeout=30
            ) as reopened:
                assert (
                    reopened.get("/api/v1/settings/model-routing").json()["rules"]
                    == saved.json()["rules"]
                )
                assert (
                    reopened.get(f"/api/v1/models/{model_id}").json()["parameters"]["temperature"]
                    == 0.7
                )
            assert (
                client.delete(
                    f"/api/v1/providers/{real.json()['id']}",
                    headers={**headers, "If-Match": real.headers["etag"]},
                ).status_code
                == 204
            )
            with Session(engine) as db:
                assert (
                    db.get(ProviderConnection, uuid.UUID(real.json()["id"])).encrypted_credential
                    is None
                )
            assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204
    finally:
        with Session(engine) as db:
            db.execute(delete(User).where(User.id == owner))
            db.commit()
        engine.dispose()
