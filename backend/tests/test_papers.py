import os
import time
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_auth import ORIGIN, PASSWORD, sign_in
from test_auth import account_client as account_client

from researchos.cli import provision_user
from researchos.domain.models import PaperFile, StorageCleanup
from researchos.infrastructure.storage import LocalFileStore
from researchos.services.maintenance import reconcile_storage
from researchos.services.papers import cleanup_storage

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("RESEARCHOS_RUN_INTEGRATION") != "1", reason="Live PG required"),
]


def pdf_fixture(marker="Fixture"):
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] /Contents 4 0 R /Resources << >> >>",
        b"<< /Length 0 >>\nstream\n\nendstream",
        f"<< /Producer ({marker}) >>".encode(),
    ]
    data = b"%PDF-1.7\n"
    offsets = [0]
    for i, body in enumerate(objects, 1):
        offsets.append(len(data))
        data += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(data)
    data += f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode()
    for offset in offsets[1:]:
        data += f"{offset:010} 00000 n \n".encode()
    return (
        data
        + (
            f"trailer\n<< /Size {len(offsets)} /Root 1 0 R /Info 5 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n"
        ).encode()
    )


@pytest.fixture
def library(account_client, tmp_path):
    client, connection = account_client
    client.app.state.settings.storage_root = tmp_path
    login = sign_in(client)
    headers = {**ORIGIN, "X-CSRF-Token": login.json()["csrf_token"]}
    return client, connection, headers, tmp_path


def upload(client, headers, *, key=None, data=None, project=None, filename="fixture.pdf"):
    return client.post(
        "/api/v1/papers/upload",
        params={"filename": filename, **({"project_id": project} if project else {})},
        headers={
            **headers,
            "Content-Type": "application/pdf",
            "Idempotency-Key": key or str(uuid.uuid4()),
        },
        content=data or pdf_fixture(),
    )


def test_upload_replay_dedup_search_and_range_download(library):
    client, _, headers, storage = library
    project = client.post("/api/v1/projects", headers=headers, json={"name": "Study"}).json()["id"]
    first = upload(client, headers, key="retry-key", project=project, filename="../../original.pdf")
    assert first.status_code == 201, first.text
    paper = first.json()["paper"]
    assert paper["original_name"] == "original.pdf" and paper["project_ids"] == [project]
    assert "storage_key" not in first.text and first.json()["ingestion_job"] is None
    replay = upload(
        client, headers, key="retry-key", project=project, filename="../../original.pdf"
    )
    assert replay.status_code == 201 and replay.json() == first.json()
    assert upload(client, headers, key="retry-key", data=pdf_fixture("Changed")).status_code == 409
    duplicate = upload(client, headers)
    assert duplicate.status_code == 200 and duplicate.json()["duplicate"] is True
    assert duplicate.json()["paper"]["id"] == paper["id"]
    assert len(list(storage.glob("*.pdf"))) == 1
    listed = client.get("/api/v1/papers", params={"q": "original", "project_id": project}).json()[
        "items"
    ]
    assert len(listed) == 1 and listed[0]["id"] == paper["id"]
    full = client.get(f"/api/v1/papers/{paper['id']}/file")
    assert full.content == pdf_fixture() and full.headers["cache-control"] == "private, no-store"
    ranged = client.get(f"/api/v1/papers/{paper['id']}/file", headers={"Range": "bytes=0-7"})
    assert ranged.status_code == 206 and ranged.content == pdf_fixture()[:8]


def test_paper_edits_delete_and_project_delete_preserves_file(library):
    client, _, headers, storage = library
    project = client.post("/api/v1/projects", headers=headers, json={"name": "Delete membership"})
    paper = upload(client, headers, project=project.json()["id"]).json()["paper"]
    path = f"/api/v1/papers/{paper['id']}"
    current = client.get(path)
    assert client.patch(path, headers=headers, json={"title": "X"}).status_code == 428
    edited = client.patch(
        path,
        headers={**headers, "If-Match": current.headers["etag"]},
        json={"title": "Evidence study"},
    )
    assert edited.status_code == 200 and edited.json()["revision"] == 2
    assert (
        client.delete(path, headers={**headers, "If-Match": current.headers["etag"]}).status_code
        == 412
    )
    assert (
        client.delete(
            project.headers["location"], headers={**headers, "If-Match": project.headers["etag"]}
        ).status_code
        == 204
    )
    assert client.get(path).json()["project_ids"] == []
    assert client.get(path).json()["revision"] == 3
    assert client.get(path + "/file").status_code == 200
    tag = client.get(path).headers["etag"]
    assert client.delete(path, headers={**headers, "If-Match": tag}).status_code == 204
    assert client.get(path).status_code == 404 and list(storage.iterdir()) == []


def test_papers_and_files_are_inaccessible_to_other_users(library):
    client, connection, headers, _ = library
    paper = upload(client, headers).json()["paper"]
    path = f"/api/v1/papers/{paper['id']}"
    with Session(connection, join_transaction_mode="create_savepoint") as db:
        provision_user(db, "paper-other@example.invalid", PASSWORD)
        db.commit()
    login = client.post(
        "/api/v1/auth/login",
        headers=ORIGIN,
        json={"email": "paper-other@example.invalid", "password": PASSWORD},
    )
    other = {**ORIGIN, "X-CSRF-Token": login.json()["csrf_token"], "If-Match": f'"{paper["id"]}:1"'}
    assert client.get("/api/v1/papers").json()["items"] == []
    assert client.get(path).status_code == 404 and client.get(path + "/file").status_code == 404
    assert client.patch(path, headers=other, json={"title": "Stolen"}).status_code == 404
    assert client.delete(path, headers=other).status_code == 404
    separate = upload(client, other)
    assert separate.status_code == 201 and separate.json()["paper"]["id"] != paper["id"]


def test_invalid_uploads_do_not_leave_files(library):
    client, _, headers, storage = library
    assert upload(client, headers, data=b"not pdf").status_code == 422
    assert upload(client, headers, filename="payload.exe").status_code == 422
    assert upload(client, ORIGIN).status_code == 403
    assert upload(client, headers, project=str(uuid.uuid4())).status_code == 404
    client.app.state.settings.max_upload_bytes = 1024
    assert upload(client, headers, data=b"%PDF-1.7\n" + b"x" * 1100 + b"%%EOF").status_code == 413
    assert list(storage.iterdir()) == []


def test_cleanup_failure_is_durable_and_retryable(library, monkeypatch):
    client, connection, headers, storage = library
    paper = upload(client, headers).json()["paper"]
    path = f"/api/v1/papers/{paper['id']}"
    tag = client.get(path).headers["etag"]
    original = LocalFileStore.delete

    def offline(self, key):
        raise OSError("fixture storage failure")

    monkeypatch.setattr(LocalFileStore, "delete", offline)
    assert client.delete(path, headers={**headers, "If-Match": tag}).status_code == 204
    with Session(connection, join_transaction_mode="create_savepoint") as db:
        task = db.scalar(
            select(StorageCleanup).where(
                StorageCleanup.storage_key == next(storage.glob("*.pdf")).name
            )
        )
        assert task.attempt == 1 and task.error_code == "storage_unavailable"
        assert (
            db.scalar(select(PaperFile).where(PaperFile.paper_id == uuid.UUID(paper["id"]))) is None
        )
    assert len(list(storage.glob("*.pdf"))) == 1
    monkeypatch.setattr(LocalFileStore, "delete", original)
    with Session(connection, join_transaction_mode="create_savepoint") as db:
        assert cleanup_storage(db, LocalFileStore(storage)) == 1
        assert (
            db.scalar(select(StorageCleanup).where(StorageCleanup.storage_key == task.storage_key))
            is None
        )
    assert list(storage.iterdir()) == []


def test_reconciliation_keeps_referenced_and_recent_files(library):
    client, connection, headers, storage = library
    upload(client, headers)
    retained = next(storage.glob("*.pdf"))
    old = time.time() - 25 * 3600
    os.utime(retained, (old, old))
    abandoned = storage / (uuid.uuid4().hex + ".pdf")
    abandoned.write_bytes(b"abandoned fixture")
    os.utime(abandoned, (old, old))
    pending = storage / (uuid.uuid4().hex + ".tmp")
    pending.write_bytes(b"active temporary fixture")
    unrelated = storage / "unrelated.txt"
    unrelated.write_bytes(b"fixture")
    os.utime(unrelated, (old, old))
    with Session(connection, join_transaction_mode="create_savepoint") as db:
        assert reconcile_storage(db, LocalFileStore(storage)) == {"cleaned": 0, "orphaned": 1}
    assert retained.exists() and pending.exists() and unrelated.exists() and not abandoned.exists()
