import logging
import time
from pathlib import Path

from sqlalchemy.orm import Session

from researchos.core.config import Settings
from researchos.infrastructure.database import build_engine
from researchos.infrastructure.storage import LocalFileStore
from researchos.services.maintenance import reconcile_storage


def main():
    settings = Settings()
    engine = build_engine(settings)
    store = LocalFileStore(settings.storage_root)
    logging.basicConfig(level=settings.log_level)
    try:
        while True:
            try:
                with Session(engine) as db:
                    reconcile_storage(db, store)
                Path("/tmp/researchos-maintenance-ready").touch()
            except Exception as exc:
                logging.error("maintenance_failed type=%s", type(exc).__name__)
            time.sleep(60)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
