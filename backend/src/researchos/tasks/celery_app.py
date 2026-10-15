from celery import Celery

from researchos.core.config import Settings

settings = Settings()
app = Celery(
    "researchos",
    broker=settings.redis_url.get_secret_value(),
    backend=settings.redis_url.get_secret_value(),
    include=["researchos.tasks.ingestion", "researchos.tasks.analysis"],
)
app.conf.update(
    accept_content=["json"],
    task_serializer="json",
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    broker_connection_timeout=5,
    broker_transport_options={"socket_connect_timeout": 2, "socket_timeout": 2},
    result_expires=300,
    task_soft_time_limit=20,
    task_time_limit=30,
)


@app.task(name="researchos.foundation.ping")
def ping() -> dict[str, str]:
    """Verify an actual broker-to-worker round trip without document data."""
    return {"status": "ok"}
