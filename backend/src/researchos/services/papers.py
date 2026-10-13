import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta

from fastapi.encoders import jsonable_encoder
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from researchos.api.errors import ApiError
from researchos.core.config import Settings
from researchos.domain.models import (
    DocumentVersion,
    IdempotencyRecord,
    Paper,
    PaperFigure,
    PaperFile,
    PaperProject,
    ProcessingJob,
    StorageCleanup,
    User,
)
from researchos.infrastructure.storage import FileStore, StoredUpload
from researchos.services.projects import owned_project
from researchos.services.resources import require_revision


def owned_paper(db: Session, owner: uuid.UUID, identifier: uuid.UUID, lock=False) -> Paper:
    query = select(Paper).where(Paper.owner_id == owner, Paper.id == identifier)
    if lock:
        query = query.with_for_update()
    paper = db.scalar(query)
    if paper is None:
        raise ApiError(404, "paper_not_found", "Paper not found")
    return paper


def paper_read(db: Session, paper: Paper) -> dict:
    file = db.scalar(
        select(PaperFile).where(
            PaperFile.owner_id == paper.owner_id, PaperFile.paper_id == paper.id
        )
    )
    projects = list(
        db.scalars(
            select(PaperProject.project_id).where(
                PaperProject.owner_id == paper.owner_id, PaperProject.paper_id == paper.id
            )
        )
    )
    latest = db.scalar(
        select(DocumentVersion)
        .where(DocumentVersion.owner_id == paper.owner_id, DocumentVersion.paper_id == paper.id)
        .order_by(DocumentVersion.created_at.desc(), DocumentVersion.id.desc())
        .limit(1)
    )
    job = (
        db.scalar(
            select(ProcessingJob)
            .where(
                ProcessingJob.owner_id == paper.owner_id,
                ProcessingJob.document_version_id == latest.id,
            )
            .order_by(ProcessingJob.created_at.desc())
            .limit(1)
        )
        if latest
        else None
    )
    return {
        "id": paper.id,
        "title": paper.title,
        "external_processing_allowed": paper.external_processing_allowed,
        "revision": paper.revision,
        "created_at": paper.created_at,
        "updated_at": paper.updated_at,
        "project_ids": projects,
        "original_name": file.original_name,
        "byte_size": file.byte_size,
        "sha256": file.sha256,
        "processing_state": latest.state if latest else "not_processed",
        "latest_document_version_id": latest.id if latest else None,
        "latest_ingestion_job_id": job.id if job else None,
    }


def accept_upload(
    db: Session,
    owner: uuid.UUID,
    upload: StoredUpload,
    name: str,
    project_id: uuid.UUID | None,
    key: str,
    settings: Settings,
) -> tuple[int, dict, bool]:
    # Serialize uploads for an account: replay and content deduplication commit together.
    db.scalar(select(User.id).where(User.id == owner).with_for_update())
    now = datetime.now(UTC)
    digest = hashlib.sha256(
        json.dumps([upload.sha256, name, str(project_id)], separators=(",", ":")).encode()
    ).hexdigest()
    replay = db.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.owner_id == owner,
            IdempotencyRecord.operation == "paper_upload",
            IdempotencyRecord.key == key,
        )
    )
    if replay and replay.expires_at <= now:
        db.delete(replay)
        db.flush()
        replay = None
    if replay:
        if replay.request_hash != digest:
            raise ApiError(
                409, "idempotency_conflict", "Upload key was already used for different content"
            )
        return replay.response_status, replay.response_body, False
    if project_id:
        owned_project(db, owner, project_id, lock=True)
    existing = db.scalar(
        select(PaperFile).where(PaperFile.owner_id == owner, PaperFile.sha256 == upload.sha256)
    )
    duplicate = existing is not None
    if existing:
        paper = owned_paper(db, owner, existing.paper_id, lock=True)
    else:
        paper = Paper(owner_id=owner)
        db.add(paper)
        db.flush()
        file = PaperFile(
            owner_id=owner,
            paper_id=paper.id,
            sha256=upload.sha256,
            storage_key=upload.key,
            original_name=name,
            byte_size=upload.byte_size,
        )
        db.add(file)
        db.flush()
        if settings.auto_ingest_uploads:
            from researchos.services.ingestion import enqueue_ingestion

            enqueue_ingestion(db, paper, file, settings, update_revision=False)
    if project_id and db.get(PaperProject, (owner, paper.id, project_id)) is None:
        db.add(PaperProject(owner_id=owner, paper_id=paper.id, project_id=project_id))
        if duplicate:
            paper.revision += 1
            paper.updated_at = now
    db.flush()
    from researchos.services.ingestion import job_read

    active = db.scalar(
        select(ProcessingJob).where(
            ProcessingJob.owner_id == owner,
            ProcessingJob.paper_id == paper.id,
            ProcessingJob.state.in_(["queued", "running"]),
        )
    )
    body = jsonable_encoder(
        {
            "paper": paper_read(db, paper),
            "duplicate": duplicate,
            "ingestion_job": job_read(active) if active else None,
        }
    )
    status = 200 if duplicate else 201
    db.add(
        IdempotencyRecord(
            owner_id=owner,
            operation="paper_upload",
            key=key,
            request_hash=digest,
            response_status=status,
            response_body=body,
            expires_at=now + timedelta(hours=24),
        )
    )
    db.commit()
    return status, body, not duplicate


def patch_paper(
    db: Session, owner: uuid.UUID, identifier: uuid.UUID, changes: dict, match: str | None
):
    db.scalar(select(User.id).where(User.id == owner).with_for_update())
    paper = owned_paper(db, owner, identifier, lock=True)
    require_revision(paper, match)
    if "project_ids" in changes:
        ids = changes.pop("project_ids")
        for project_id in sorted(ids):
            owned_project(db, owner, project_id, lock=True)
        db.execute(
            delete(PaperProject).where(
                PaperProject.owner_id == owner, PaperProject.paper_id == identifier
            )
        )
        for project_id in ids:
            db.add(PaperProject(owner_id=owner, paper_id=identifier, project_id=project_id))
    for key, value in changes.items():
        setattr(paper, key, value)
    paper.revision += 1
    paper.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(paper)
    return paper


def delete_paper(db: Session, owner: uuid.UUID, identifier: uuid.UUID, match: str | None):
    db.scalar(select(User.id).where(User.id == owner).with_for_update())
    paper = owned_paper(db, owner, identifier, lock=True)
    require_revision(paper, match)
    if db.scalar(
        select(ProcessingJob.id).where(
            ProcessingJob.owner_id == owner,
            ProcessingJob.paper_id == identifier,
            ProcessingJob.state.in_(["queued", "running"]),
        )
    ):
        raise ApiError(
            409,
            "processing_active",
            "Wait for document processing to finish before deleting this paper",
        )
    file = db.scalar(
        select(PaperFile).where(PaperFile.owner_id == owner, PaperFile.paper_id == identifier)
    )
    db.add(StorageCleanup(owner_id=owner, storage_key=file.storage_key))
    for key in db.scalars(
        select(PaperFigure.storage_key).where(
            PaperFigure.owner_id == owner, PaperFigure.paper_id == identifier
        )
    ):
        db.add(StorageCleanup(owner_id=owner, storage_key=key))
    db.delete(paper)
    db.commit()


def cleanup_storage(db: Session, store: FileStore, limit: int = 20) -> int:
    tasks = list(
        db.scalars(
            select(StorageCleanup)
            .order_by(StorageCleanup.attempt, StorageCleanup.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )
    count = 0
    for task in tasks:
        try:
            store.delete(task.storage_key)
        except (OSError, ValueError):
            task.attempt += 1
            task.error_code = "storage_unavailable"
        else:
            db.delete(task)
            count += 1
    db.commit()
    return count
