from contextlib import contextmanager
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError

from researchos.domain.models import SCHEMA_REVISION
from researchos.main import create_app
from researchos.services.health import InfrastructureHealth


def test_liveness_remains_available_when_dependencies_are_down(settings):
    probe = Mock()
    probe.ready.return_value = False
    with TestClient(create_app(settings, probe)) as client:
        assert client.get("/api/v1/health/live").json() == {"status": "ok"}
        response = client.get("/api/v1/health/ready")
        assert response.status_code == 503
        assert response.json() == {"status": "unavailable"}
        assert response.headers["Cache-Control"] == "private, no-store"
        assert response.headers["X-Request-ID"]


def test_unknown_route_returns_safe_consistent_error(settings):
    with TestClient(create_app(settings, Mock())) as client:
        response = client.get("/api/v1/missing?api_key=private-input")
        assert response.status_code == 404
        assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]
        assert "private-input" not in response.text


def test_unexpected_exception_does_not_leak_payload(settings, caplog):
    probe = Mock()
    probe.ready.side_effect = RuntimeError("private-provider-key-and-document")
    with TestClient(create_app(settings, probe)) as client:
        response = client.get("/api/v1/health/ready")
        assert response.status_code == 500
        assert "private-provider-key-and-document" not in response.text + caplog.text


@pytest.mark.parametrize("revision", [None, "old_revision"])
def test_unmigrated_database_is_not_ready(revision):
    engine = Mock()
    engine.connect.return_value.__enter__ = Mock(return_value=Mock())
    engine.connect.return_value.__exit__ = Mock(return_value=False)
    engine.connect.return_value.__enter__.return_value.execute.return_value.scalar.return_value = (
        revision
    )
    broker = Mock()
    assert not InfrastructureHealth(engine, broker).ready()
    broker.ping.assert_not_called()


def test_dependency_exception_is_redacted(caplog):
    @contextmanager
    def connection():
        handle = Mock()
        handle.execute.return_value.scalar.return_value = SCHEMA_REVISION
        yield handle

    engine = Mock(connect=connection)
    broker = Mock()
    broker.ping.side_effect = ConnectionError("redis://private-password@host")
    assert not InfrastructureHealth(engine, broker).ready()
    assert "private-password" not in caplog.text
