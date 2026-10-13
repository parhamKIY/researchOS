import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from researchos.api.errors import ApiError
from researchos.core.config import Settings
from researchos.domain.models import (
    DocumentVersion,
    IdempotencyRecord,
    Paper,
    PaperFile,
    ProcessingJob,
    User,
)
from researchos.processing.contracts import ParseLimits
from researchos.processing.identity import PARSER_NAME, parser_version


def parser_policy(settings: Settings) -> dict:
    return {
        "limits": ParseLimits(
            max_pages=settings.parse_max_pages, max_figures=settings.parse_max_figures
        ).model_dump(),
        "timeout_seconds": settings.parse_timeout_seconds,
        "memory_mb": settings.parse_memory_mb,
    }


def owned_job(db: Session, owner: uuid.UUID, identifier: uuid.UUID, lock=False) -> ProcessingJob:
    query = select(ProcessingJob).where(
        ProcessingJob.owner_id == owner, ProcessingJob.id == identifier
    )
    job = db.scalar(query.with_for_update() if lock else query)
    if job is None:
        raise ApiError(404, "job_not_found", "Processing job not found")
    return job


def job_read(job: ProcessingJob) -> dict:
    return {
        "id": str(job.id),
        "paper_id": str(job.paper_id),
        "document_version_id": str(job.document_version_id),
        "kind": job.kind,
        "state": job.state,
        "stage": job.stage,
        "progress_percent": job.progress_percent,
        "attempt": job.attempt,
        "retry_of_job_id": str(job.retry_of_job_id) if job.retry_of_job_id else None,
        "error": {"code": job.error_code} if job.error_code else None,
        "created_at": job.created_at.isoformat(),
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


def enqueue_ingestion(
    db: Session,
    paper: Paper,
    file: PaperFile,
    settings: Settings,
    retry_of: uuid.UUID | None = None,
    update_revision: bool = True,
) -> ProcessingJob:
    active = db.scalar(
        select(ProcessingJob.id).where(
            ProcessingJob.owner_id == paper.owner_id,
            ProcessingJob.paper_id == paper.id,
            ProcessingJob.state.in_(["queued", "running"]),
        )
    )
    if active:
        raise ApiError(409, "ingestion_already_running", "Document processing is already active")
    now = datetime.now(UTC)
    count = db.scalar(
        select(func.count())
        .select_from(ProcessingJob)
        .where(
            ProcessingJob.owner_id == paper.owner_id,
            ProcessingJob.created_at >= now - timedelta(hours=1),
        )
    )
    if count >= 60:
        raise ApiError(
            429,
            "processing_rate_limited",
            "Document processing limit reached; try again later",
            {"Retry-After": "3600"},
        )
    policy = parser_policy(settings)
    identity = {
        "name": PARSER_NAME,
        "version": parser_version(),
        "config": policy,
        "file_sha256": file.sha256,
    }
    fingerprint = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    version = DocumentVersion(
        owner_id=paper.owner_id,
        paper_id=paper.id,
        file_id=file.id,
        parser_name=PARSER_NAME,
        parser_version=identity["version"],
        parser_config=policy,
        created_at=now,
    )
    db.add(version)
    db.flush()
    job = ProcessingJob(
        owner_id=paper.owner_id,
        paper_id=paper.id,
        document_version_id=version.id,
        fingerprint=fingerprint,
        snapshot=identity,
        retry_of_job_id=retry_of,
        created_at=now,
    )
    db.add(job)
    db.flush()
    if update_revision:
        paper.revision += 1
        paper.updated_at = now
    return job


def request_ingestion(
    db: Session,
    owner: uuid.UUID,
    paper_id: uuid.UUID,
    key: str,
    settings: Settings,
    retry_of: uuid.UUID | None = None,
) -> dict:
    db.scalar(select(User.id).where(User.id == owner).with_for_update())
    paper = db.scalar(
        select(Paper).where(Paper.owner_id == owner, Paper.id == paper_id).with_for_update()
    )
    if paper is None:
        raise ApiError(404, "paper_not_found", "Paper not found")
    operation = "ingestion_retry" if retry_of else "paper_ingestion"
    digest = hashlib.sha256(
        json.dumps(
            [str(paper_id), str(retry_of), parser_policy(settings), parser_version()],
            sort_keys=True,
        ).encode()
    ).hexdigest()
    previous = db.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.owner_id == owner,
            IdempotencyRecord.operation == operation,
            IdempotencyRecord.key == key,
        )
    )
    if previous and previous.expires_at <= datetime.now(UTC):
        db.delete(previous)
        db.flush()
        previous = None
    if previous:
        if previous.request_hash != digest:
            raise ApiError(
                409,
                "idempotency_conflict",
                "Request key was already used for a different operation",
            )
        return previous.response_body
    if retry_of:
        old = owned_job(db, owner, retry_of, lock=True)
        if old.paper_id != paper_id or old.state != "failed":
            raise ApiError(409, "job_not_retryable", "Only a failed ingestion can be retried")
    file = db.scalar(
        select(PaperFile).where(PaperFile.owner_id == owner, PaperFile.paper_id == paper_id)
    )
    job = enqueue_ingestion(db, paper, file, settings, retry_of)
    db.flush()
    body = job_read(job)
    db.add(
        IdempotencyRecord(
            owner_id=owner,
            operation=operation,
            key=key,
            request_hash=digest,
            response_status=202,
            response_body=body,
            expires_at=datetime.now(UTC) + timedelta(hours=24),
        )
    )
    db.commit()
    return body


@dataclass
class JobLease:
    id: uuid.UUID
    owner_id: uuid.UUID
    paper_id: uuid.UUID
    version_id: uuid.UUID
    token: uuid.UUID
    file_key: str
    snapshot: dict


def locked_job(db: Session, identifier: uuid.UUID) -> ProcessingJob | None:
    root = db.execute(
        select(ProcessingJob.owner_id, ProcessingJob.paper_id).where(ProcessingJob.id == identifier)
    ).first()
    if root is None:
        return None
    db.scalar(select(User.id).where(User.id == root.owner_id).with_for_update())
    db.scalar(
        select(Paper.id)
        .where(Paper.id == root.paper_id, Paper.owner_id == root.owner_id)
        .with_for_update()
    )
    return db.scalar(select(ProcessingJob).where(ProcessingJob.id == identifier).with_for_update())


def claim_job(db: Session, identifier: uuid.UUID, settings: Settings) -> JobLease | None:
    job = locked_job(db, identifier)
    if job is None or job.state != "queued":
        db.rollback()
        return None
    version = db.get(DocumentVersion, job.document_version_id)
    file = db.get(PaperFile, version.file_id)
    now = datetime.now(UTC)
    if not db.scalar(select(User.is_active).where(User.id == job.owner_id)):
        job.state = "failed"
        job.error_code = "account_disabled"
        job.finished_at = now
        version.state = "failed"
        version.warnings = ["account_disabled"]
        version.completed_at = now
        db.commit()
        return None
    job.state = "running"
    job.stage = "parsing"
    job.attempt += 1
    job.progress_percent = 0
    job.error_code = None
    job.started_at = job.started_at or now
    job.lease_token = uuid.uuid4()
    job.heartbeat_at = now
    job.lease_expires_at = now + timedelta(seconds=settings.job_lease_seconds)
    version.state = "processing"
    lease = JobLease(
        job.id,
        job.owner_id,
        job.paper_id,
        version.id,
        job.lease_token,
        file.storage_key,
        job.snapshot,
    )
    db.commit()
    return lease


def heartbeat_job(db: Session, lease: JobLease, settings: Settings, progress: int) -> bool:
    from sqlalchemy import update

    now = datetime.now(UTC)
    result = db.execute(
        update(ProcessingJob)
        .where(
            ProcessingJob.id == lease.id,
            ProcessingJob.state == "running",
            ProcessingJob.lease_token == lease.token,
            ProcessingJob.lease_expires_at > now,
        )
        .values(
            heartbeat_at=now,
            lease_expires_at=now + timedelta(seconds=settings.job_lease_seconds),
            progress_percent=func.greatest(ProcessingJob.progress_percent, min(progress, 95)),
        )
    )
    db.commit()
    return result.rowcount == 1


def fail_job(db: Session, lease: JobLease, code: str) -> bool:
    job = locked_job(db, lease.id)
    if not owns_lease(job, lease):
        db.rollback()
        return False
    job.state = "failed"
    job.error_code = code
    job.finished_at = datetime.now(UTC)
    job.lease_token = job.lease_expires_at = None
    version = db.get(DocumentVersion, lease.version_id)
    version.state = "failed"
    version.warnings = [code]
    version.completed_at = job.finished_at
    db.commit()
    return True


def owns_lease(job: ProcessingJob | None, lease: JobLease) -> bool:
    return bool(
        job
        and job.state == "running"
        and job.lease_token == lease.token
        and job.lease_expires_at > datetime.now(UTC)
    )
