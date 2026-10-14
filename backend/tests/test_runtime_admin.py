import os
import uuid
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from researchos.cli import provision_user
from researchos.core.config import Settings
from researchos.domain.models import SystemLLMSettings, SystemProviderCandidate, User
from researchos.infrastructure.database import build_engine

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RESEARCHOS_RUN_INTEGRATION") != "1", reason="Live stack required"
    ),
]


def test_live_admin_proxy_mock_activation_access_controls_and_cleanup():
    settings = Settings()
    engine = build_engine(settings)
    prefix = uuid.uuid4().hex
    email, regular_email = (
        f"admin-runtime-{prefix}@example.invalid",
        f"regular-runtime-{prefix}@example.invalid",
    )
    password = "Disposable admin runtime fixture password"
    with Session(engine) as db:
        owner = provision_user(db, email, password, is_admin=True).id
        regular = provision_user(db, regular_email, password).id
        db.commit()
    active_id, active_revision = None, None
    try:
        with httpx.Client(base_url="http://frontend:3000", timeout=30) as client:
            assert client.get("/admin").status_code == 200
            assert client.get("/api/v1/admin/llm").status_code == 401
            origin = {"Origin": str(settings.public_origin).rstrip("/")}
            signed_in = client.post(
                "/api/v1/auth/login", headers=origin, json={"email": email, "password": password}
            )
            assert signed_in.status_code == 200 and signed_in.json()["user"]["is_admin"]
            headers = {**origin, "X-CSRF-Token": signed_in.json()["csrf_token"]}
            current = client.get("/api/v1/admin/llm")
            assert current.status_code == 200 and "encrypted_credential" not in current.text
            # Never replace a provider configured by a human during a test run.
            if current.json()["active"] is None:
                result = client.post(
                    "/api/v1/admin/llm/verify-and-apply",
                    headers={**headers, "If-Match": current.json()["etag"]},
                    json={"adapter": "mock", "model_name": f"runtime-fixture-{prefix}"},
                )
                assert result.status_code == 200 and result.json()["applied"], result.text
                active_id = uuid.UUID(result.json()["settings"]["active"]["id"])
                active_revision = result.json()["settings"]["revision"]
                assert result.json()["check"]["execution_mode"] == "mock"
                rejected = client.post(
                    "/api/v1/admin/llm/verify-and-apply",
                    headers={**headers, "If-Match": result.json()["settings"]["etag"]},
                    json={
                        "adapter": "openai_compatible",
                        "base_url": "http://127.0.0.1",
                        "api_key": "explicit-runtime-fixture-key",
                        "model_name": "fixture",
                    },
                )
                assert (
                    rejected.status_code == 422
                    and "explicit-runtime-fixture-key" not in rejected.text
                )
                assert client.get("/api/v1/admin/llm").json()["active"]["id"] == str(active_id)
            signed_in = client.post(
                "/api/v1/auth/login",
                headers=origin,
                json={"email": regular_email, "password": password},
            )
            assert signed_in.status_code == 200 and not signed_in.json()["user"]["is_admin"]
            assert client.get("/api/v1/admin/overview").status_code == 403
            assert client.get("/api/v1/admin/users").status_code == 403
            assert (
                client.post(
                    "/api/v1/admin/llm/verify-and-apply",
                    headers={**origin, "X-CSRF-Token": signed_in.json()["csrf_token"]},
                    json={"adapter": "mock", "model_name": "forbidden"},
                ).status_code
                == 403
            )
            public = client.get("/api/v1/settings/system-model")
            assert public.status_code == 200 and "checks" not in public.json()
            if active_id:
                assert (
                    public.json()["active"]["id"] == str(active_id)
                    and "credential_configured" not in public.text
                )
    finally:
        with Session(engine) as db, db.begin():
            current = db.query(SystemLLMSettings).filter_by(id=1).with_for_update().one()
            if (
                active_id
                and current.active_candidate_id == active_id
                and current.revision == active_revision
            ):
                current.active_candidate_id = None
                current.revision += 1
                current.updated_at = datetime.now(UTC)
                db.flush()
            query = delete(SystemProviderCandidate).where(
                SystemProviderCandidate.created_by == owner
            )
            if current.active_candidate_id:
                query = query.where(SystemProviderCandidate.id != current.active_candidate_id)
            db.execute(query)
            db.execute(delete(User).where(User.id.in_([owner, regular])))
        engine.dispose()
