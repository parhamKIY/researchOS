import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Header, Request, Response
from pydantic import BaseModel, ConfigDict

from researchos.api.dependencies import Authenticated, Database, Mutation
from researchos.services.ingestion import job_read, owned_job, request_ingestion

router = APIRouter(prefix="/api/v1", tags=["Document processing"])
UploadKey = Annotated[str, Header(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")]


class JobRead(BaseModel):
    id: uuid.UUID
    paper_id: uuid.UUID
    document_version_id: uuid.UUID
    kind: Literal["ingestion"]
    state: Literal["queued", "running", "completed", "partially_completed", "failed"]
    stage: str | None
    progress_percent: int
    attempt: int
    retry_of_job_id: uuid.UUID | None
    error: dict[str, str] | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class IngestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


@router.post("/papers/{paper_id}/ingestions", status_code=202, response_model=JobRead)
def ingest(
    paper_id: uuid.UUID,
    payload: IngestionRequest,
    request: Request,
    response: Response,
    db: Database,
    identity: Mutation,
    idempotency_key: UploadKey,
):
    body = request_ingestion(
        db, identity.user.id, paper_id, idempotency_key, request.app.state.settings
    )
    response.headers["Location"] = f"/api/v1/jobs/{body['id']}"
    return body


@router.get("/jobs/{job_id}", response_model=JobRead)
def read(job_id: uuid.UUID, db: Database, identity: Authenticated):
    return job_read(owned_job(db, identity.user.id, job_id))


@router.post("/jobs/{job_id}/retry", status_code=202, response_model=JobRead)
def retry(
    job_id: uuid.UUID,
    payload: IngestionRequest,
    request: Request,
    response: Response,
    db: Database,
    identity: Mutation,
    idempotency_key: UploadKey,
):
    old = owned_job(db, identity.user.id, job_id)
    body = request_ingestion(
        db,
        identity.user.id,
        old.paper_id,
        idempotency_key,
        request.app.state.settings,
        retry_of=job_id,
    )
    response.headers["Location"] = f"/api/v1/jobs/{body['id']}"
    return body
