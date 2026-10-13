import re
import shutil
import time
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from researchos.domain.models import IdempotencyRecord, PaperFigure, PaperFile
from researchos.infrastructure.storage import LocalFileStore
from researchos.services.papers import cleanup_storage


def reconcile_storage(db: Session, store: LocalFileStore) -> dict:
    cleaned = cleanup_storage(db, store)
    db.execute(delete(IdempotencyRecord).where(IdempotencyRecord.expires_at <= datetime.now(UTC)))
    referenced = set(db.scalars(select(PaperFile.storage_key)))
    referenced.update(db.scalars(select(PaperFigure.storage_key)))
    db.commit()
    cutoff = time.time() - 24 * 3600
    orphaned = 0
    if store.root.exists():
        for path in store.root.iterdir():
            if not re.fullmatch(r"[a-f0-9]{32}\.(pdf|png|tmp)", path.name) or path.is_symlink():
                continue
            try:
                if path.name not in referenced and path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
                    orphaned += 1
            except OSError:
                continue
    working_root = store.root / ".processing"
    if (
        working_root.exists()
        and not working_root.is_symlink()
        and working_root.resolve().parent == store.root
    ):
        for candidate in working_root.iterdir():
            if candidate.is_symlink() or not re.fullmatch(r"parse-[a-z0-9_]{8}", candidate.name):
                continue
            try:
                if (
                    candidate.resolve().parent == working_root.resolve()
                    and candidate.stat().st_mtime < cutoff
                ):
                    shutil.rmtree(candidate)
            except OSError:
                pass
    return {"cleaned": cleaned, "orphaned": orphaned}
