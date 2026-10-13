import pytest

from researchos.core.config import Settings


@pytest.fixture
def settings():
    return Settings(
        _env_file=None,
        environment="test",
        database_url="postgresql+psycopg://fixture:fixture@127.0.0.1:9/fixture",
        redis_url="redis://127.0.0.1:9/0",
        session_secret="unit-test-secret-that-is-not-a-real-credential",
    )
