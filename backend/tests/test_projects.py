import os
import uuid

import pytest
from sqlalchemy.orm import Session
from test_auth import ORIGIN, PASSWORD, sign_in
from test_auth import account_client as account_client

from researchos.cli import provision_user

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("RESEARCHOS_RUN_INTEGRATION") != "1", reason="Live PG required"),
]


def authorized(client):
    response = sign_in(client)
    return {**ORIGIN, "X-CSRF-Token": response.json()["csrf_token"]}


def test_project_lifecycle_revisions_archive_and_delete(account_client):
    client, _ = account_client
    headers = authorized(client)
    first = client.post("/api/v1/projects", headers=headers, json={"name": " My project "})
    assert first.status_code == 201, first.text
    path = first.headers["location"]
    tag = first.headers["etag"]
    assert first.json()["name"] == "My project"
    for invalid in [{}, {"name": None}, {"description": None}, {"archived": None}]:
        assert (
            client.patch(path, headers={**headers, "If-Match": tag}, json=invalid).status_code
            == 422
        )
    assert "owner_id" not in first.json()
    assert client.get(path).headers["etag"] == tag
    assert client.patch(path, headers=headers, json={"name": "Updated"}).status_code == 428
    changed = client.patch(
        path, headers={**headers, "If-Match": tag}, json={"name": "Updated", "archived": True}
    )
    assert changed.status_code == 200 and changed.json()["revision"] == 2
    assert client.get("/api/v1/projects").json()["items"] == []
    assert len(client.get("/api/v1/projects?archived=true").json()["items"]) == 1
    assert client.delete(path, headers={**headers, "If-Match": tag}).status_code == 412
    assert (
        client.delete(path, headers={**headers, "If-Match": changed.headers["etag"]}).status_code
        == 204
    )
    assert client.get(path).status_code == 404


def test_projects_never_cross_account_boundaries(account_client):
    client, connection = account_client
    headers = authorized(client)
    resource = client.post("/api/v1/projects", headers=headers, json={"name": "Private"})
    path = resource.headers["location"]
    with Session(connection, join_transaction_mode="create_savepoint") as db:
        provision_user(db, "other@example.invalid", PASSWORD)
        db.commit()
    login = client.post(
        "/api/v1/auth/login",
        headers=ORIGIN,
        json={"email": "other@example.invalid", "password": PASSWORD},
    )
    other = {
        **ORIGIN,
        "X-CSRF-Token": login.json()["csrf_token"],
        "If-Match": resource.headers["etag"],
    }
    assert client.get("/api/v1/projects").json()["items"] == []
    assert client.get(path).status_code == 404
    assert client.patch(path, headers=other, json={"name": "Stolen"}).status_code == 404
    assert client.delete(path, headers=other).status_code == 404
    assert client.get(f"/api/v1/projects/{uuid.uuid4()}").status_code == 404


def test_project_pagination_and_input_controls(account_client):
    client, _ = account_client
    headers = authorized(client)
    for name in ["A", "B", "C"]:
        assert (
            client.post("/api/v1/projects", headers=headers, json={"name": name}).status_code == 201
        )
    first = client.get("/api/v1/projects?limit=2").json()
    second = client.get(
        "/api/v1/projects", params={"limit": 2, "cursor": first["next_cursor"]}
    ).json()
    assert len(first["items"]) == 2 and len(second["items"]) == 1
    assert not set(p["id"] for p in first["items"]) & set(p["id"] for p in second["items"])
    assert (
        client.get(
            "/api/v1/projects",
            params={"limit": 2, "archived": True, "cursor": first["next_cursor"]},
        ).status_code
        == 422
    )
    assert client.get("/api/v1/projects?cursor=bad").status_code == 422
    assert client.post("/api/v1/projects", headers=headers, json={"name": " "}).status_code == 422
    assert (
        client.post(
            "/api/v1/projects", headers=headers, json={"name": "X", "owner_id": str(uuid.uuid4())}
        ).status_code
        == 422
    )
    assert (
        client.post("/api/v1/projects", headers=ORIGIN, json={"name": "No CSRF"}).status_code == 403
    )
    assert client.post("/api/v1/projects", headers=headers, content=b"x" * 17000).status_code == 413
