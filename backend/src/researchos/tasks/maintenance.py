import logging
import time
from pathlib import Path

from sqlalchemy.orm import Session

from researchos.core.config import Settings
from researchos.infrastructure.database import build_engine
from researchos.infrastructure.storage import LocalFileStore
from researchos.services.dispatch import dispatch_ready_jobs, recover_expired_jobs
from researchos.services.maintenance import reconcile_storage
from researchos.tasks.celery_app import app


def main():
    settings = Settings()
    engine = build_engine(settings)
    store = LocalFileStore(settings.storage_root)
    logging.basicConfig(level=settings.log_level)
    last_sweep = -1
    try:
        while True:
            try:
                with Session(engine) as db:
                    recover_expired_jobs(db)
                    dispatch_ready_jobs(db, app)
                    if int(time.monotonic()) // 60 != last_sweep:
                        reconcile_storage(db, store)
                        last_sweep = int(time.monotonic()) // 60
                Path("/tmp/researchos-maintenance-ready").touch()
            except Exception as exc:
                logging.error("maintenance_failed type=%s", type(exc).__name__)
            time.sleep(5)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
