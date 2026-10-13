import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from researchos.core.config import Settings
from researchos.domain.models import AuthSession, User
from researchos.infrastructure.database import build_engine
from researchos.main import create_app

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RESEARCHOS_RUN_INTEGRATION") != "1", reason="Live infrastructure opt-in required"
    ),
]


@pytest.fixture
def infrastructure_settings():
    return Settings()


@pytest.fixture
def connection(infrastructure_settings):
    engine = build_engine(infrastructure_settings)
    with engine.connect() as handle:
        transaction = handle.begin()
        yield handle
        transaction.rollback()
    engine.dispose()


def new_user(email="foundation-test@example.invalid"):
    return User(email_normalized=email, password_hash="test-fixture-not-a-password-hash")


def test_migration_matches_sqlalchemy_metadata():
    command.check(Config("alembic.ini"))


def test_identity_persistence_and_session_cascade(connection):
    with Session(connection) as session:
        user = new_user()
        session.add(user)
        session.flush()
        token = AuthSession(
            owner_id=user.id,
            token_hash="a" * 64,
            csrf_token_hash="b" * 64,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        session.add(token)
        session.flush()
        assert session.scalar(select(AuthSession.owner_id)) == user.id
        session.execute(delete(User).where(User.id == user.id))
        assert session.scalar(select(AuthSession.id)) is None


@pytest.mark.parametrize("case", ["unnormalized", "duplicate", "orphan_session"])
def test_database_rejects_invalid_identity_relations(connection, case):
    with Session(connection) as session:
        if case == "duplicate":
            session.add(new_user())
            session.flush()
        with pytest.raises(IntegrityError), session.begin_nested():
            if case == "orphan_session":
                session.add(
                    AuthSession(
                        owner_id=uuid.uuid4(),
                        token_hash="c" * 64,
                        csrf_token_hash="d" * 64,
                        expires_at=datetime.now(UTC) + timedelta(hours=1),
                    )
                )
            else:
                session.add(
                    new_user(
                        "Uppercase@example.invalid"
                        if case == "unnormalized"
                        else "foundation-test@example.invalid"
                    )
                )
            session.flush()


def test_api_readiness_with_live_postgresql_and_redis(infrastructure_settings):
    with TestClient(create_app(infrastructure_settings)) as client:
        assert client.get("/api/v1/health/ready").status_code == 200


def test_real_celery_broker_worker_result_round_trip():
    from researchos.tasks.celery_app import app

    result = app.send_task("researchos.foundation.ping")
    try:
        assert result.get(timeout=20) == {"status": "ok"}
    finally:
        result.forget()
