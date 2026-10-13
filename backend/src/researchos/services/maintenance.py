import re
import time
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from researchos.domain.models import IdempotencyRecord, PaperFile
from researchos.infrastructure.storage import LocalFileStore
from researchos.services.papers import cleanup_storage


def reconcile_storage(db: Session, store: LocalFileStore) -> dict:
    cleaned = cleanup_storage(db, store)
    db.execute(delete(IdempotencyRecord).where(IdempotencyRecord.expires_at <= datetime.now(UTC)))
    referenced = set(db.scalars(select(PaperFile.storage_key)))
    db.commit()
    cutoff = time.time() - 24 * 3600
    orphaned = 0
    if store.root.exists():
        for path in store.root.iterdir():
            if not re.fullmatch(r"[a-f0-9]{32}\.(pdf|tmp)", path.name) or path.is_symlink():
                continue
            try:
                if path.name not in referenced and path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
                    orphaned += 1
            except OSError:
                continue
    return {"cleaned": cleaned, "orphaned": orphaned}
