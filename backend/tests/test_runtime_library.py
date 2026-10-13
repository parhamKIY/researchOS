import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from test_papers import pdf_fixture

from researchos.cli import provision_user
from researchos.core.config import Settings
from researchos.domain.models import PaperFile, User
from researchos.infrastructure.database import build_engine
from researchos.infrastructure.storage import LocalFileStore

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RESEARCHOS_RUN_INTEGRATION") != "1", reason="Live stack required"
    ),
]


def test_live_frontend_proxy_large_upload_and_duplicate_race():
    settings = Settings()
    engine = build_engine(settings)
    email = f"runtime-{uuid.uuid4().hex}@example.invalid"
    password = "Disposable runtime verification fixture"
    with Session(engine) as db:
        user_id = provision_user(db, email, password).id
        db.commit()
    try:
        with httpx.Client(base_url="http://frontend:3000", timeout=60) as client:
            origin = {"Origin": str(settings.public_origin).rstrip("/")}
            assert (
                client.post(
                    "/api/v1/auth/login",
                    headers=origin,
                    json={"email": email, "password": password},
                ).status_code
                == 200
            )
            session = client.get("/api/v1/auth/session").json()
            headers = {**origin, "X-CSRF-Token": session["csrf_token"]}
            project = client.post(
                "/api/v1/projects", headers=headers, json={"name": "Runtime proxy fixture"}
            )
            assert project.status_code == 201
            data = pdf_fixture(padding=11 * 1024 * 1024)

            def send(key):
                return client.post(
                    "/api/v1/papers/upload",
                    params={"filename": "large-fixture.pdf", "project_id": project.json()["id"]},
                    content=data,
                    headers={**headers, "Content-Type": "application/pdf", "Idempotency-Key": key},
                )

            with ThreadPoolExecutor(max_workers=2) as pool:
                responses = list(pool.map(send, ["race-first", "race-second"]))
            assert sorted(r.status_code for r in responses) == [200, 201], [
                r.status_code for r in responses
            ]
            identifiers = {r.json()["paper"]["id"] for r in responses}
            assert len(identifiers) == 1
            paper_id = identifiers.pop()
            read = client.get(f"/api/v1/papers/{paper_id}")
            assert read.json()["byte_size"] == len(data)
            with httpx.Client(
                base_url="http://frontend:3000", cookies=client.cookies, timeout=30
            ) as reopened:
                assert (
                    reopened.get(
                        "/api/v1/papers", params={"project_id": project.json()["id"]}
                    ).json()["items"][0]["id"]
                    == paper_id
                )
                ranged = reopened.get(
                    f"/api/v1/papers/{paper_id}/file", headers={"Range": "bytes=0-7"}
                )
                assert ranged.status_code == 206 and ranged.content == b"%PDF-1.7"
            assert (
                client.delete(
                    f"/api/v1/papers/{paper_id}",
                    headers={**headers, "If-Match": read.headers["etag"]},
                ).status_code
                == 204
            )
            assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204
            assert client.get("/api/v1/auth/session").status_code == 401
    finally:
        with Session(engine) as db:
            keys = list(
                db.scalars(select(PaperFile.storage_key).where(PaperFile.owner_id == user_id))
            )
            for key in keys:
                LocalFileStore(settings.storage_root).delete(key)
            db.execute(delete(User).where(User.id == user_id))
            db.commit()
        engine.dispose()
