import os
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_auth import ORIGIN, PASSWORD, sign_in
from test_auth import account_client as account_client

from researchos.cli import grant_admin, provision_user
from researchos.domain.models import AuthSession, User

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("RESEARCHOS_RUN_INTEGRATION") != "1", reason="Live PG required"),
]


@pytest.fixture
def admin_client(account_client):
    client, connection = account_client
    with Session(connection, join_transaction_mode="create_savepoint") as db:
        grant_admin(db, "account@example.invalid")
        regular = provision_user(db, "admin-target@example.invalid", PASSWORD)
        regular_id = regular.id
        db.commit()
    login = sign_in(client)
    assert login.json()["user"]["is_admin"] is True
    return client, connection, {**ORIGIN, "X-CSRF-Token": login.json()["csrf_token"]}, regular_id


def test_only_explicit_admin_has_access_and_role_is_checked_live(account_client):
    client, connection = account_client
    assert client.get("/api/v1/admin/overview").status_code == 401
    login = sign_in(client)
    assert login.json()["user"]["is_admin"] is False
    assert client.get("/api/v1/admin/users").status_code == 403
    with Session(connection, join_transaction_mode="create_savepoint") as db:
        grant_admin(db, "account@example.invalid")
        db.commit()
    assert client.get("/api/v1/admin/overview").status_code == 200
    with Session(connection, join_transaction_mode="create_savepoint") as db:
        db.scalar(
            select(User).where(User.email_normalized == "account@example.invalid")
        ).is_admin = False
        db.commit()
    assert client.get("/api/v1/admin/overview").status_code == 403


def test_admin_status_revision_csrf_protection_and_session_revocation(admin_client):
    client, connection, headers, target = admin_client
    target_login = client.post(
        "/api/v1/auth/login",
        headers=ORIGIN,
        json={"email": "admin-target@example.invalid", "password": PASSWORD},
    )
    target_cookie = client.cookies.get("researchos_session")
    assert target_login.status_code == 200
    headers["X-CSRF-Token"] = sign_in(client).json()["csrf_token"]
    users = client.get("/api/v1/admin/users").json()["items"]
    regular = next(row for row in users if row["id"] == str(target))
    route = f"/api/v1/admin/users/{target}"
    assert all("password_hash" not in row for row in users)
    assert client.patch(route, headers=ORIGIN, json={"is_active": False}).status_code == 403
    assert client.patch(route, headers=headers, json={"is_active": False}).status_code == 428
    edit = {**headers, "If-Match": regular["etag"]}
    assert client.patch(route, headers=edit, json={"is_admin": True}).status_code == 422
    disabled = client.patch(route, headers=edit, json={"is_active": False})
    assert disabled.status_code == 200 and disabled.json()["is_active"] is False
    assert client.patch(route, headers=edit, json={"is_active": True}).status_code == 412
    admin = next(row for row in users if row["is_admin"])
    assert (
        client.patch(
            f"/api/v1/admin/users/{admin['id']}",
            headers={**headers, "If-Match": admin["etag"]},
            json={"is_active": False},
        ).status_code
        == 409
    )
    with Session(connection) as db:
        assert all(
            row.revoked_at
            for row in db.scalars(select(AuthSession).where(AuthSession.owner_id == target))
        )
    assert (
        client.patch(
            route,
            headers={**headers, "If-Match": disabled.json()["etag"]},
            json={"is_active": True},
        ).status_code
        == 200
    )
    client.cookies.set("researchos_session", target_cookie)
    assert client.get("/api/v1/auth/session").status_code == 401
    assert uuid.UUID(admin["id"]) != target
