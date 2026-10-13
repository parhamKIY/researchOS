from sqlalchemy import Engine, create_engine

from researchos.core.config import Settings


def build_engine(settings: Settings) -> Engine:
    return create_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        pool_timeout=settings.health_timeout_seconds,
        connect_args={
            "connect_timeout": settings.health_timeout_seconds,
            "options": f"-c statement_timeout={settings.health_timeout_seconds * 1000}",
        },
    )
