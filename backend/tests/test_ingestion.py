import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pdf_fixtures import scientific_fixture
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_auth import account_client as account_client
from test_papers import library as library
from test_papers import upload

from researchos.domain.models import DocumentPage, DocumentVersion, PaperFigure, ProcessingJob
from researchos.infrastructure.storage import LocalFileStore
from researchos.processing.contracts import ParseLimits
from researchos.processing.pypdf_adapter import PypdfParser
from researchos.services.dispatch import dispatch_ready_jobs, recover_expired_jobs
from researchos.services.ingestion import claim_job, fail_job, heartbeat_job
from researchos.services.publication import publish_document

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("RESEARCHOS_RUN_INTEGRATION") != "1", reason="Live PG required"),
]


@pytest.fixture
def queued(library, tmp_path):
    client, connection, headers, storage = library
    client.app.state.settings.auto_ingest_uploads = True
    source = tmp_path / "input" / "fixture.pdf"
    source.parent.mkdir()
    scientific_fixture(source)
    result = upload(client, headers, data=source.read_bytes())
    assert result.status_code == 201, result.text
    return client, connection, headers, storage, source, result.json()


def database(connection):
    return Session(connection, join_transaction_mode="create_savepoint")


def test_queue_claim_publication_and_duplicate_delivery(queued, tmp_path):
    client, connection, headers, storage, source, body = queued
    identifier = uuid.UUID(body["ingestion_job"]["id"])
    paper_id = body["paper"]["id"]
    tag = client.get(f"/api/v1/papers/{paper_id}").headers["etag"]
    assert (
        client.delete(
            f"/api/v1/papers/{paper_id}", headers={**headers, "If-Match": tag}
        ).status_code
        == 409
    )
    with database(connection) as db:
        lease = claim_job(db, identifier, client.app.state.settings)
        assert lease is not None
        assert claim_job(db, identifier, client.app.state.settings) is None
        assert heartbeat_job(db, lease, client.app.state.settings, 40)
    parsed = PypdfParser().parse(source, tmp_path / "parsed", ParseLimits(), lambda *_: None)
    with database(connection) as db:
        assert publish_document(db, lease, parsed, tmp_path / "parsed", LocalFileStore(storage))
        assert not publish_document(db, lease, parsed, tmp_path / "parsed", LocalFileStore(storage))
        assert (
            len(
                list(
                    db.scalars(
                        select(DocumentPage).where(
                            DocumentPage.document_version_id == lease.version_id
                        )
                    )
                )
            )
            == 2
        )
        assert (
            len(
                list(
                    db.scalars(
                        select(PaperFigure).where(
                            PaperFigure.document_version_id == lease.version_id
                        )
                    )
                )
            )
            == 2
        )
    job = client.get(f"/api/v1/jobs/{identifier}").json()
    assert job["state"] == "completed" and job["progress_percent"] == 100
    assert "snapshot" not in job and "lease_token" not in job
    fresh = client.get(f"/api/v1/papers/{paper_id}")
    assert fresh.json()["processing_state"] == "ready"
    version_id = fresh.json()["latest_document_version_id"]
    document = client.get(f"/api/v1/document-versions/{version_id}").json()
    assert document["page_count"] == 2 and document["figure_count"] == 2
    assert "owner_id" not in document
    page = client.get(f"/api/v1/document-versions/{version_id}/pages/1").json()
    assert page["text_status"] == "available"
    sections = client.get(f"/api/v1/document-versions/{version_id}/sections").json()["items"]
    assert sections and all(section["spans"] for section in sections)
    figures = client.get(
        f"/api/v1/papers/{paper_id}/figures?document_version_id={version_id}"
    ).json()["items"]
    assert len(figures) == 2
    image = client.get(figures[0]["file_url"])
    assert image.status_code == 200 and image.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert image.headers["cache-control"] == "private, no-store"
    assert client.get(f"/api/v1/document-versions/{version_id}/pages/0").status_code == 404
    assert (
        client.get(
            f"/api/v1/papers/{uuid.uuid4()}/figures?document_version_id={version_id}"
        ).status_code
        == 404
    )
    assert (
        client.delete(
            f"/api/v1/papers/{paper_id}", headers={**headers, "If-Match": fresh.headers["etag"]}
        ).status_code
        == 204
    )
    assert not list(storage.glob("*.png"))


def test_expired_lease_recovery_fences_old_worker(queued):
    client, connection, _, _, _, body = queued
    identifier = uuid.UUID(body["ingestion_job"]["id"])
    settings = client.app.state.settings
    with database(connection) as db:
        old = claim_job(db, identifier, settings)
        row = db.get(ProcessingJob, identifier)
        row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
        assert not fail_job(db, old, "fixture_old_worker")
        assert recover_expired_jobs(db) == 1
        new = claim_job(db, identifier, settings)
        assert new.token != old.token
        assert not heartbeat_job(db, old, settings, 80)
        assert not fail_job(db, old, "fixture_old_worker")
        assert heartbeat_job(db, new, settings, 50)
        assert fail_job(db, new, "invalid_pdf")


def test_retry_creates_new_version_and_replays_request(queued):
    client, connection, headers, _, _, body = queued
    identifier = uuid.UUID(body["ingestion_job"]["id"])
    with database(connection) as db:
        lease = claim_job(db, identifier, client.app.state.settings)
        assert fail_job(db, lease, "invalid_pdf")
    route = f"/api/v1/jobs/{identifier}/retry"
    key_headers = {**headers, "Idempotency-Key": "safe-retry"}
    response = client.post(route, headers=key_headers, json={})
    assert response.status_code == 202, response.text
    assert response.json()["document_version_id"] != str(lease.version_id)
    assert response.json()["retry_of_job_id"] == str(identifier)
    assert client.post(route, headers=key_headers, json={}).json() == response.json()
    active = client.post(
        f"/api/v1/papers/{lease.paper_id}/ingestions",
        headers={**headers, "Idempotency-Key": "other"},
        json={},
    )
    assert active.status_code == 409
    with database(connection) as db:
        assert db.get(DocumentVersion, lease.version_id).state == "failed"
        assert (
            len(
                list(
                    db.scalars(
                        select(DocumentVersion).where(DocumentVersion.paper_id == lease.paper_id)
                    )
                )
            )
            == 2
        )


def test_broker_failure_leaves_durable_job_for_later_dispatch(queued):
    _, connection, _, _, _, body = queued
    identifier = uuid.UUID(body["ingestion_job"]["id"])

    class OfflinePublisher:
        def send_task(self, *args, **kwargs):
            raise OSError("Explicit test broker outage")

    class RecordingPublisher:
        def __init__(self):
            self.messages = []

        def send_task(self, name, **kwargs):
            self.messages.append((name, kwargs))

    with database(connection) as db:
        assert dispatch_ready_jobs(db, OfflinePublisher()) == 0
        row = db.get(ProcessingJob, identifier)
        assert row.state == "queued"
        row.dispatch_after = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
        publisher = RecordingPublisher()
        assert dispatch_ready_jobs(db, publisher) == 1
        assert publisher.messages == [
            (
                "researchos.ingestion.run",
                {"args": [str(identifier)], "ignore_result": True, "retry": False},
            )
        ]
        assert row.state == "queued"
