import hashlib
import logging
import tempfile
import time
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from researchos.core.config import Settings
from researchos.infrastructure.database import build_engine
from researchos.infrastructure.storage import LocalFileStore
from researchos.processing.contracts import ParseFailure, ParseLimits
from researchos.processing.identity import PARSER_NAME, parser_version
from researchos.processing.runner import parse_in_process
from researchos.services.ingestion import claim_job, fail_job, heartbeat_job
from researchos.services.publication import publish_document
from researchos.tasks.celery_app import app

logger = logging.getLogger(__name__)


@app.task(
    name="researchos.ingestion.run",
    ignore_result=True,
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=240,
    time_limit=270,
)
def run_ingestion(job_id: str) -> dict:
    try:
        identifier = uuid.UUID(job_id)
    except (ValueError, TypeError):
        return {"status": "ignored"}
    settings = Settings()
    engine = build_engine(settings)
    lease = None
    try:
        with Session(engine) as db:
            lease = claim_job(db, identifier, settings)
        if lease is None:
            return {"status": "ignored"}
        if (lease.snapshot["name"], lease.snapshot["version"]) != (PARSER_NAME, parser_version()):
            raise ParseFailure("parser_version_unavailable")
        store = LocalFileStore(settings.storage_root)
        source = store.path(lease.file_key)
        try:
            with source.open("rb") as handle:
                digest = hashlib.file_digest(handle, "sha256").hexdigest()
        except OSError:
            raise ParseFailure("storage_unavailable") from None
        if digest != lease.snapshot["file_sha256"]:
            raise ParseFailure("source_integrity_mismatch")
        working_root = store.root / ".processing"
        working_root.mkdir(exist_ok=True, mode=0o700)
        if working_root.is_symlink() or working_root.resolve().parent != store.root:
            raise ParseFailure("storage_unavailable")
        last = 0.0

        def heartbeat(current, total):
            nonlocal last
            now = time.monotonic()
            if now - last < 2:
                return True
            with Session(engine) as db:
                valid = heartbeat_job(
                    db, lease, settings, int(90 * current / total) if total else 0
                )
            last = now
            return valid

        with tempfile.TemporaryDirectory(prefix="parse-", dir=working_root) as temporary:
            config = lease.snapshot["config"]
            parsed = parse_in_process(
                source,
                Path(temporary),
                ParseLimits.model_validate(config["limits"]),
                timeout_seconds=config["timeout_seconds"],
                memory_mb=config["memory_mb"],
                heartbeat=heartbeat,
            )
            with Session(engine) as db:
                published = publish_document(db, lease, parsed, Path(temporary), store)
        return {"status": "completed" if published else "ignored"}
    except Exception as exc:
        code = exc.code if isinstance(exc, ParseFailure) else "processing_failed"
        if lease and code != "lease_lost":
            try:
                with Session(engine) as db:
                    fail_job(db, lease, code)
            except Exception as failure:
                logger.error("ingestion_state_write_failed type=%s", type(failure).__name__)
        logger.warning("ingestion_failed code=%s", code)
        return {"status": "failed"}
    finally:
        engine.dispose()
