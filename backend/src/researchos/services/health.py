import logging
from typing import Protocol

from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from researchos.domain.models import SCHEMA_REVISION

logger = logging.getLogger(__name__)


class HealthProbe(Protocol):
    def ready(self) -> bool: ...


class InfrastructureHealth:
    def __init__(self, engine: Engine, broker: Redis):
        self.engine = engine
        self.broker = broker

    def ready(self) -> bool:
        try:
            with self.engine.connect() as connection:
                revision = connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar()
                if revision != SCHEMA_REVISION:
                    return False
            return bool(self.broker.ping())
        except (SQLAlchemyError, RedisError):
            logger.warning("readiness_unavailable")
            return False
