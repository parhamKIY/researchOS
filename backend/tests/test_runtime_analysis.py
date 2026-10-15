"""Real frontend/API/queue/worker path; optionally retain an isolated restart fixture."""

import json
import os
import time
import uuid
from pathlib import Path

import httpx
import pytest
from pdf_fixtures import scientific_fixture
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from test_runtime_ingestion import wait_job

from researchos.cli import provision_user
from researchos.core.config import Settings
from researchos.domain.models import PaperFigure, PaperFile, User
from researchos.infrastructure.database import build_engine
from researchos.infrastructure.storage import LocalFileStore

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RESEARCHOS_RUN_INTEGRATION") != "1", reason="Live stack required"
    ),
]


def cleanup_fixture(settings, owners):
    engine = build_engine(settings)
    owner_ids = [uuid.UUID(value) for value in owners]
    store = LocalFileStore(settings.storage_root)
    with Session(engine) as db:
        keys = list(
            db.scalars(select(PaperFile.storage_key).where(PaperFile.owner_id.in_(owner_ids)))
        )
        keys += list(
            db.scalars(select(PaperFigure.storage_key).where(PaperFigure.owner_id.in_(owner_ids)))
        )
        db.execute(delete(User).where(User.id.in_(owner_ids)))
        db.commit()
        for key in keys:
            store.delete(key)
    engine.dispose()


def verify_retained_fixture(state_path):
    path = Path(state_path)
    state = json.loads(path.read_text())
    settings = Settings()
    try:
        with httpx.Client(base_url="http://frontend:3000", timeout=30) as client:
            login = client.post(
                "/api/v1/auth/login",
                headers={"Origin": str(settings.public_origin).rstrip("/")},
                json={"email": state["email"], "password": state["password"]},
            )
            assert login.status_code == 200
            for identifier in state["reports"]:
                response = client.get(f"/api/v1/analyses/{identifier}")
                assert response.status_code == 200 and response.json()["state"] == "completed"
                assert len(response.json()["sections"]) == len(response.json()["usage"]) == 7
        print("Stored reports survived container recreation; isolated fixture cleaned.")
    finally:
        cleanup_fixture(settings, state["owners"])
        path.unlink()


def test_live_analysis_consent_celery_evidence_history_and_isolation(tmp_path):
    from researchos.tasks.celery_app import app

    settings = Settings()
    engine = build_engine(settings)
    suffix = uuid.uuid4().hex
    password = "Disposable analysis runtime fixture password"
    email = f"analysis-runtime-{suffix}@example.invalid"
    stranger_email = f"analysis-stranger-{suffix}@example.invalid"
    owners, reports = [], []
    retained = False
    state_path = os.getenv("RESEARCHOS_PERSISTENCE_STATE")
    if state_path and Path(state_path).exists():
        pytest.fail(
            "Persistence fixture path already exists; preserve it for explicit verification"
        )
    with Session(engine) as db:
        owners = [
            str(provision_user(db, address, password).id) for address in [email, stranger_email]
        ]
        db.commit()
    try:
        with httpx.Client(base_url="http://frontend:3000", timeout=60) as client:
            origin = {"Origin": str(settings.public_origin).rstrip("/")}
            login = client.post(
                "/api/v1/auth/login", headers=origin, json={"email": email, "password": password}
            )
            assert login.status_code == 200
            headers = {**origin, "X-CSRF-Token": login.json()["csrf_token"]}
            project = client.post(
                "/api/v1/projects",
                headers=headers,
                json={"name": "Explicit analysis runtime fixture"},
            )
            assert project.status_code == 201
            source = tmp_path / "analysis-fixture.pdf"
            scientific_fixture(source)
            upload = client.post(
                f"/api/v1/papers/upload?filename=analysis-fixture.pdf&project_id={project.json()['id']}",
                headers={**headers, "Content-Type": "application/pdf", "Idempotency-Key": suffix},
                content=source.read_bytes(),
            )
            assert upload.status_code == 201, upload.text
            paper = upload.json()["paper"]["id"]
            version = wait_job(client, upload.json()["ingestion_job"]["id"])["document_version_id"]
            provider = client.post(
                "/api/v1/providers",
                headers=headers,
                json={"adapter": "mock", "display_name": "Explicit runtime mock"},
            )
            assert provider.status_code == 201
            model = client.post(
                f"/api/v1/providers/{provider.json()['id']}/models",
                headers=headers,
                json={"model_name": "runtime-analysis-fixture", "capabilities": ["text"]},
            )
            assert model.status_code == 201
            routing = client.get("/api/v1/settings/model-routing")
            saved = client.put(
                "/api/v1/settings/model-routing",
                headers={**headers, "If-Match": routing.headers["etag"]},
                json={
                    "rules": [
                        {
                            "task": task,
                            "primary_model_id": model.json()["id"],
                            "allowed_provider_ids": [provider.json()["id"]],
                        }
                        for task in ["paper_summary", "methodology", "research_gaps"]
                    ]
                },
            )
            assert saved.status_code == 200
            for language in ["fa", "en"]:
                plan = client.get(
                    f"/api/v1/papers/{paper}/analysis-plan",
                    params={"document_version_id": version, "language": language},
                )
                assert plan.status_code == 200 and not plan.json()["external_required"]
                body = {
                    "document_version_id": version,
                    "language": language,
                    "plan_fingerprint": plan.json()["fingerprint"],
                    "approved_configuration_ids": [
                        item["configuration_id"] for item in plan.json()["targets"]
                    ],
                }
                start_headers = {**headers, "Idempotency-Key": f"{suffix}-{language}"}
                queued = client.post(
                    f"/api/v1/papers/{paper}/analyses", headers=start_headers, json=body
                )
                assert queued.status_code == 202, queued.text
                assert (
                    client.post(
                        f"/api/v1/papers/{paper}/analyses", headers=start_headers, json=body
                    ).json()
                    == queued.json()
                )
                identifier = queued.json()["id"]
                reports.append(identifier)
                # Deliberately duplicate delivery; only one worker may publish or charge.
                for _ in range(2):
                    app.send_task(
                        "researchos.analysis.run",
                        args=[identifier],
                        ignore_result=True,
                        retry=False,
                    )
                deadline = time.monotonic() + 45
                detail = None
                while time.monotonic() < deadline:
                    response = client.get(f"/api/v1/analyses/{identifier}")
                    assert response.status_code == 200
                    detail = response.json()
                    if detail["state"] not in {"queued", "running"}:
                        break
                    time.sleep(0.5)
                assert detail["state"] == "completed", detail
                assert len(detail["sections"]) == len(detail["usage"]) == 7
                for part in detail["sections"]:
                    assert part["payload"]["generation"]["execution_mode"] == "mock"
                    for claim in part["payload"]["items"]:
                        for witness in claim["evidence"]:
                            page = client.get(
                                f"/api/v1/document-versions/{version}/pages/{witness['page_number']}"
                            ).json()
                            assert page["id"] == witness["page_id"]
                            assert (
                                page["text"][witness["start_offset"] : witness["end_offset"]]
                                == witness["quote"]
                            )
            assert len(client.get(f"/api/v1/papers/{paper}/analyses").json()["items"]) == 2
            with httpx.Client(base_url="http://frontend:3000", timeout=30) as stranger:
                assert (
                    stranger.post(
                        "/api/v1/auth/login",
                        headers=origin,
                        json={"email": stranger_email, "password": password},
                    ).status_code
                    == 200
                )
                assert stranger.get(f"/api/v1/analyses/{reports[0]}").status_code == 404
                assert stranger.get(f"/api/v1/papers/{paper}/analyses").status_code == 404
            if state_path:
                path = Path(state_path)
                path.parent.mkdir(exist_ok=True)
                path.write_text(
                    json.dumps(
                        {"email": email, "password": password, "owners": owners, "reports": reports}
                    )
                )
                retained = True
    finally:
        if not retained:
            cleanup_fixture(settings, owners)
        engine.dispose()
