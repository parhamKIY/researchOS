import os
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError
from sqlalchemy import select
from sqlalchemy.orm import Session

from researchos.api.auth import login_limit
from researchos.api.dependencies import get_db
from researchos.cli import provision_user
from researchos.core.config import Settings
from researchos.core.security import token_hash
from researchos.domain.models import AuthSession, User
from researchos.infrastructure.database import build_engine
from researchos.main import create_app

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("RESEARCHOS_RUN_INTEGRATION") != "1", reason="Live PG required"),
]
PASSWORD = "integration fixture password"
ORIGIN = {"Origin": "http://localhost:3000"}


@pytest.fixture
def account_client():
    engine = build_engine(Settings())
    with engine.connect() as connection:
        outer = connection.begin()
        with Session(connection, join_transaction_mode="create_savepoint") as db:
            provision_user(db, "account@example.invalid", PASSWORD)
            db.commit()
        app = create_app(Settings())

        def database_override():
            with Session(connection, join_transaction_mode="create_savepoint") as db:
                yield db

        app.dependency_overrides[get_db] = database_override
        # Explicitly bypass rate limiting here; it has separate Redis-backed tests.
        app.dependency_overrides[login_limit] = lambda: None
        with TestClient(app) as client:
            yield client, connection
        outer.rollback()
    engine.dispose()


def sign_in(client):
    response = client.post(
        "/api/v1/auth/login",
        headers=ORIGIN,
        json={"email": " ACCOUNT@example.invalid ", "password": PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response


def test_auth_lifecycle_cookie_csrf_and_revocation(account_client):
    client, connection = account_client
    assert client.get("/api/v1/auth/session").status_code == 401
    response = sign_in(client)
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Domain=" not in cookie
    token = client.cookies.get("researchos_session")
    with Session(connection) as db:
        stored = db.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash(token)))
        assert stored.token_hash == token_hash(token)
        assert stored.csrf_token_hash == token_hash(response.json()["csrf_token"])
        assert stored.token_hash != token
    assert client.get("/api/v1/auth/session").json() == response.json()
    assert client.post("/api/v1/auth/logout", headers=ORIGIN).status_code == 403
    assert (
        client.post(
            "/api/v1/auth/logout", headers={**ORIGIN, "X-CSRF-Token": "wrong-token"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/auth/logout",
            headers={
                "Origin": "https://attacker.invalid",
                "X-CSRF-Token": response.json()["csrf_token"],
            },
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/auth/logout",
            headers={**ORIGIN, "X-CSRF-Token": response.json()["csrf_token"]},
        ).status_code
        == 204
    )
    client.cookies.set("researchos_session", token)
    assert client.get("/api/v1/auth/session").status_code == 401


def test_login_rejects_origin_and_hides_invalid_credentials(account_client):
    client, _ = account_client
    payload = {"email": "account@example.invalid", "password": "wrong"}
    assert client.post("/api/v1/auth/login", json=payload).status_code == 403
    first = client.post("/api/v1/auth/login", headers=ORIGIN, json=payload)
    payload["email"] = "absent@example.invalid"
    second = client.post("/api/v1/auth/login", headers=ORIGIN, json=payload)
    assert first.status_code == second.status_code == 401
    assert first.json()["error"]["message"] == second.json()["error"]["message"]
    assert "wrong" not in first.text and "account@example.invalid" not in first.text


@pytest.mark.parametrize("case", ["expired", "inactive", "rotated"])
def test_session_invalidations(account_client, case):
    client, connection = account_client
    sign_in(client)
    old = client.cookies.get("researchos_session")
    with Session(connection, join_transaction_mode="create_savepoint") as db:
        if case == "inactive":
            db.scalar(
                select(User).where(User.email_normalized == "account@example.invalid")
            ).is_active = False
        elif case == "expired":
            session = db.scalar(
                select(AuthSession).where(AuthSession.token_hash == token_hash(old))
            )
            session.created_at = datetime.now(UTC) - timedelta(days=2)
            session.expires_at = datetime.now(UTC) - timedelta(days=1)
        db.commit()
    if case == "rotated":
        sign_in(client)
        assert client.cookies.get("researchos_session") != old
        client.cookies.set("researchos_session", old)
    assert client.get("/api/v1/auth/session").status_code == 401


def test_login_limiter_fails_closed_and_preserves_retry_header(account_client, monkeypatch):
    client, _ = account_client
    client.app.dependency_overrides.pop(login_limit)
    monkeypatch.setattr(client.app.state.broker, "eval", lambda *args: 31)
    response = client.post(
        "/api/v1/auth/login", headers=ORIGIN, json={"email": "a", "password": "b"}
    )
    assert response.status_code == 429 and response.headers["retry-after"] == "60"

    def offline(*args):
        raise ConnectionError("fixture secret must not be exposed")

    monkeypatch.setattr(client.app.state.broker, "eval", offline)
    assert (
        client.post(
            "/api/v1/auth/login", headers=ORIGIN, json={"email": "a", "password": "b"}
        ).status_code
        == 503
    )
