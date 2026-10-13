import os
import time
import uuid

import httpx
import pytest
from pdf_fixtures import scientific_fixture
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from researchos.cli import provision_user
from researchos.core.config import Settings
from researchos.domain.models import DocumentPage, PaperFigure, PaperFile, User
from researchos.infrastructure.database import build_engine
from researchos.infrastructure.storage import LocalFileStore
from researchos.tasks.celery_app import app

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RESEARCHOS_RUN_INTEGRATION") != "1", reason="Live stack required"
    ),
]


def wait_job(client, identifier):
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/jobs/{identifier}")
        assert response.status_code == 200, response.text
        job = response.json()
        if job["state"] not in {"queued", "running"}:
            return job
        time.sleep(0.5)
    pytest.fail("Worker did not finish the durable job within 45 seconds")


def test_live_celery_version_history_private_evidence_and_retry(tmp_path):
    settings = Settings()
    engine = build_engine(settings)
    suffix = uuid.uuid4().hex
    password = "Disposable ingestion verification fixture"
    owners = []
    with Session(engine) as db:
        for name in ["owner", "stranger"]:
            owners.append(provision_user(db, f"{name}-{suffix}@example.invalid", password).id)
        db.commit()
    try:
        with (
            httpx.Client(base_url="http://frontend:3000", timeout=60) as client,
            httpx.Client(base_url="http://frontend:3000", timeout=30) as stranger,
        ):
            origin = {"Origin": str(settings.public_origin).rstrip("/")}
            for connection, name in [(client, "owner"), (stranger, "stranger")]:
                assert (
                    connection.post(
                        "/api/v1/auth/login",
                        headers=origin,
                        json={"email": f"{name}-{suffix}@example.invalid", "password": password},
                    ).status_code
                    == 200
                )
            headers = {
                **origin,
                "X-CSRF-Token": client.get("/api/v1/auth/session").json()["csrf_token"],
            }
            source = tmp_path / "fixture.pdf"
            scientific_fixture(source)
            response = client.post(
                "/api/v1/papers/upload?filename=fixture.pdf",
                content=source.read_bytes(),
                headers={
                    **headers,
                    "Content-Type": "application/pdf",
                    "Idempotency-Key": "scientific-fixture",
                },
            )
            assert response.status_code == 201, response.text
            paper_id = response.json()["paper"]["id"]
            job_id = response.json()["ingestion_job"]["id"]
            job = wait_job(client, job_id)
            assert job["state"] == "completed" and job["progress_percent"] == 100, job
            version_id = job["document_version_id"]
            page_route = f"/api/v1/document-versions/{version_id}/pages/1"
            page = client.get(page_route).json()
            assert "Introduction" in page["text"]
            sections = client.get(f"/api/v1/document-versions/{version_id}/sections").json()[
                "items"
            ]
            for section in sections:
                for span in section["spans"]:
                    text = client.get(
                        f"/api/v1/document-versions/{version_id}/pages/{span['page_number']}"
                    ).json()["text"]
                    assert text[span["start_offset"] : span["end_offset"]]
            figures = client.get(
                f"/api/v1/papers/{paper_id}/figures?document_version_id={version_id}"
            ).json()["items"]
            assert len(figures) == 2
            assert client.get(figures[0]["file_url"]).content.startswith(b"\x89PNG\r\n\x1a\n")
            for route in [
                page_route,
                figures[0]["file_url"],
                f"/api/v1/jobs/{job_id}",
                f"/api/v1/document-versions/{version_id}",
                f"/api/v1/document-versions/{version_id}/sections",
                f"/api/v1/papers/{paper_id}/document-versions",
            ]:
                assert stranger.get(route).status_code == 404
            app.send_task("researchos.ingestion.run", args=[job_id], ignore_result=True)
            reparse = client.post(
                f"/api/v1/papers/{paper_id}/ingestions",
                json={},
                headers={**headers, "Idempotency-Key": "reparse"},
            )
            assert reparse.status_code == 202, reparse.text
            second = wait_job(client, reparse.json()["id"])
            assert second["state"] == "completed" and second["document_version_id"] != version_id
            assert client.get(page_route).json() == page
            history = client.get(f"/api/v1/papers/{paper_id}/document-versions").json()
            assert len(history["items"]) == 2
            with Session(engine) as db:
                assert (
                    len(
                        list(
                            db.scalars(
                                select(DocumentPage).where(
                                    DocumentPage.document_version_id == uuid.UUID(version_id)
                                )
                            )
                        )
                    )
                    == 2
                )
            bad = client.post(
                "/api/v1/papers/upload?filename=invalid.pdf",
                content=b"%PDF-1.7\nThis is a deliberately malformed test fixture.\n%%EOF",
                headers={
                    **headers,
                    "Content-Type": "application/pdf",
                    "Idempotency-Key": "invalid-fixture",
                },
            )
            assert bad.status_code == 201
            failed = wait_job(client, bad.json()["ingestion_job"]["id"])
            assert failed["state"] == "failed" and failed["error"]["code"] == "invalid_pdf"
            retry = client.post(
                f"/api/v1/jobs/{failed['id']}/retry",
                json={},
                headers={**headers, "Idempotency-Key": "retry-fixture"},
            )
            assert retry.status_code == 202
            retried = wait_job(client, retry.json()["id"])
            assert retried["state"] == "failed" and retried["retry_of_job_id"] == failed["id"]
    finally:
        with Session(engine) as db:
            keys = list(
                db.scalars(select(PaperFile.storage_key).where(PaperFile.owner_id.in_(owners)))
            )
            keys += list(
                db.scalars(select(PaperFigure.storage_key).where(PaperFigure.owner_id.in_(owners)))
            )
            db.execute(delete(User).where(User.id.in_(owners)))
            db.commit()
            for key in keys:
                LocalFileStore(settings.storage_root).delete(key)
        engine.dispose()
