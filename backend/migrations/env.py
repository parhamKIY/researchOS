from alembic import context

from researchos.core.config import Settings
from researchos.domain.models import Base
from researchos.infrastructure.database import build_engine

settings = Settings()

if context.is_offline_mode():
    context.configure(
        url=settings.database_url.get_secret_value(),
        target_metadata=Base.metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = build_engine(settings)
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=Base.metadata)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()
