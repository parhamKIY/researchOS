from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from researchos.domain.models import DocumentVersion, ProcessingJob
from researchos.services.ingestion import locked_job


def recover_expired_jobs(db: Session) -> int:
    now = datetime.now(UTC)
    ids = list(
        db.scalars(
            select(ProcessingJob.id)
            .where(ProcessingJob.state == "running", ProcessingJob.lease_expires_at <= now)
            .limit(20)
        )
    )
    recovered = 0
    for identifier in ids:
        job = locked_job(db, identifier)
        if job is None or job.state != "running" or job.lease_expires_at > now:
            db.rollback()
            continue
        version = db.get(DocumentVersion, job.document_version_id)
        job.lease_token = job.lease_expires_at = None
        job.error_code = "worker_interrupted"
        job.stage = None
        job.progress_percent = 0
        if job.attempt < 3:
            job.state = "queued"
            job.dispatch_after = now
            version.state = "queued"
        else:
            job.state = "failed"
            job.error_code = "worker_unavailable"
            job.finished_at = now
            version.state = "failed"
            version.completed_at = now
            version.warnings = ["worker_unavailable"]
        db.commit()
        recovered += 1
    return recovered


def dispatch_ready_jobs(db: Session, publisher) -> int:
    now = datetime.now(UTC)
    jobs = list(
        db.scalars(
            select(ProcessingJob)
            .where(ProcessingJob.state == "queued", ProcessingJob.dispatch_after <= now)
            .order_by(ProcessingJob.created_at)
            .limit(20)
            .with_for_update(skip_locked=True)
        )
    )
    sent = 0
    for job in jobs:
        try:
            publisher.send_task(
                "researchos.ingestion.run", args=[str(job.id)], ignore_result=True, retry=False
            )
        except Exception:
            job.dispatch_after = now + timedelta(seconds=10)
            break
        else:
            job.dispatch_after = now + timedelta(seconds=60)
            sent += 1
    db.commit()
    return sent
