import logging
import uuid

from sqlalchemy.orm import Session

from researchos.core.config import Settings
from researchos.infrastructure.database import build_engine
from researchos.services.analysis_worker import execute_analysis
from researchos.tasks.celery_app import app


@app.task(
    name="researchos.analysis.run",
    ignore_result=True,
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=330,
    time_limit=360,
)
def run_analysis(report_id):
    engine = None
    try:
        identifier = uuid.UUID(report_id)
        settings = Settings()
        engine = build_engine(settings)
        return execute_analysis(identifier, settings, lambda: Session(engine))
    except Exception as exc:
        logging.warning("analysis_interrupted type=%s", type(exc).__name__)
        # Maintenance fences the expired lease and never replays a possibly paid request.
        return {"status": "interrupted"}
    finally:
        if engine is not None:
            engine.dispose()
