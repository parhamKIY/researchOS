import re
import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Header, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import or_, select
from starlette.concurrency import run_in_threadpool

from researchos.api.dependencies import Authenticated, Database, Mutation
from researchos.api.errors import ApiError
from researchos.domain.models import Paper, PaperFile, PaperProject
from researchos.infrastructure.storage import LocalFileStore
from researchos.services.papers import (
    accept_upload,
    cleanup_storage,
    delete_paper,
    owned_paper,
    paper_read,
    patch_paper,
)
from researchos.services.projects import owned_project
from researchos.services.resources import cursor_filter, cursor_scope, encode_cursor, etag

router = APIRouter(prefix="/api/v1/papers", tags=["Paper library"])


class PaperRead(BaseModel):
    id: uuid.UUID
    title: str | None
    external_processing_allowed: bool
    project_ids: list[uuid.UUID]
    original_name: str
    byte_size: int
    sha256: str
    processing_state: Literal["not_processed"]
    latest_document_version_id: uuid.UUID | None
    latest_ingestion_job_id: uuid.UUID | None
    revision: int
    created_at: datetime
    updated_at: datetime


class PaperPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, max_length=500)
    project_ids: list[uuid.UUID] | None = Field(default=None, max_length=100)
    external_processing_allowed: bool | None = None

    @model_validator(mode="after")
    def valid_changes(self):
        if not self.model_fields_set:
            raise ValueError("Provide at least one field")
        if "title" in self.model_fields_set and self.title is not None:
            self.title = self.title.strip()
            if not self.title:
                raise ValueError("Title cannot be blank")
        for name in ["project_ids", "external_processing_allowed"]:
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError("Only title may be cleared")
        if self.project_ids and len(set(self.project_ids)) != len(self.project_ids):
            raise ValueError("Duplicate project IDs")
        return self


class UploadRead(BaseModel):
    paper: PaperRead
    duplicate: bool
    ingestion_job: None


class PaperList(BaseModel):
    items: list[PaperRead]
    next_cursor: str | None


@router.post(
    "/upload",
    response_model=UploadRead,
    status_code=201,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}},
        },
    },
)
async def upload(
    request: Request,
    db: Database,
    identity: Mutation,
    filename: Annotated[str, Query(min_length=1, max_length=255)],
    idempotency_key: Annotated[str, Header(min_length=1, max_length=128)],
    project_id: uuid.UUID | None = None,
):
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/pdf":
        raise ApiError(415, "pdf_required", "Upload requires application/pdf")
    if re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", idempotency_key) is None:
        raise ApiError(422, "invalid_upload_key", "Upload key is invalid")
    name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(char for char in name if ord(char) >= 32 and ord(char) != 127).strip()
    if not name.lower().endswith(".pdf"):
        raise ApiError(422, "invalid_filename", "File name must end with .pdf")
    if project_id:
        await run_in_threadpool(owned_project, db, identity.user.id, project_id)
    store = LocalFileStore(request.app.state.settings.storage_root)
    accepted = await store.accept(request.stream(), request.app.state.settings.max_upload_bytes)
    retained = False
    try:
        status, body, retained = await run_in_threadpool(
            accept_upload, db, identity.user.id, accepted, name, project_id, idempotency_key
        )
        return JSONResponse(
            status_code=status,
            content=body,
            headers={"Location": f"/api/v1/papers/{body['paper']['id']}"},
        )
    finally:
        if not retained:
            store.delete(accepted.key)


@router.get("", response_model=PaperList)
def listing(
    request: Request,
    db: Database,
    identity: Authenticated,
    q: Annotated[str, Query(max_length=200)] = "",
    project_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
):
    if project_id:
        owned_project(db, identity.user.id, project_id)
    query = (
        select(Paper)
        .join(PaperFile, (PaperFile.paper_id == Paper.id) & (PaperFile.owner_id == Paper.owner_id))
        .where(Paper.owner_id == identity.user.id)
    )
    if project_id:
        query = query.where(
            select(PaperProject.paper_id)
            .where(
                PaperProject.owner_id == identity.user.id,
                PaperProject.paper_id == Paper.id,
                PaperProject.project_id == project_id,
            )
            .exists()
        )
    if q:
        query = query.where(
            or_(
                Paper.title.icontains(q, autoescape=True),
                PaperFile.original_name.icontains(q, autoescape=True),
            )
        )
    scope = cursor_scope(
        identity.user.id, "papers", {"q": q, "project_id": str(project_id), "limit": limit}
    )
    secret = request.app.state.settings.session_secret.get_secret_value()
    if cursor:
        query = query.where(cursor_filter(Paper, cursor, scope, secret))
    rows = list(
        db.scalars(query.order_by(Paper.created_at.desc(), Paper.id.desc()).limit(limit + 1))
    )
    return {
        "items": [paper_read(db, paper) for paper in rows[:limit]],
        "next_cursor": encode_cursor(rows[limit - 1], scope, secret) if len(rows) > limit else None,
    }


@router.get("/{paper_id}", response_model=PaperRead)
def read(paper_id: uuid.UUID, response: Response, db: Database, identity: Authenticated):
    paper = owned_paper(db, identity.user.id, paper_id)
    response.headers["ETag"] = etag(paper)
    return paper_read(db, paper)


@router.patch("/{paper_id}", response_model=PaperRead)
def patch(
    paper_id: uuid.UUID,
    payload: PaperPatch,
    response: Response,
    db: Database,
    identity: Mutation,
    if_match: Annotated[str | None, Header()] = None,
):
    paper = patch_paper(
        db, identity.user.id, paper_id, payload.model_dump(exclude_unset=True), if_match
    )
    response.headers["ETag"] = etag(paper)
    return paper_read(db, paper)


@router.delete("/{paper_id}", status_code=204)
def remove(
    paper_id: uuid.UUID,
    request: Request,
    db: Database,
    identity: Mutation,
    if_match: Annotated[str | None, Header()] = None,
):
    delete_paper(db, identity.user.id, paper_id, if_match)
    cleanup_storage(db, LocalFileStore(request.app.state.settings.storage_root))


@router.get("/{paper_id}/file", response_class=FileResponse)
def file(
    paper_id: uuid.UUID,
    request: Request,
    db: Database,
    identity: Authenticated,
    download: bool = False,
):
    owned_paper(db, identity.user.id, paper_id)
    record = db.scalar(
        select(PaperFile).where(
            PaperFile.owner_id == identity.user.id, PaperFile.paper_id == paper_id
        )
    )
    path = LocalFileStore(request.app.state.settings.storage_root).path(record.storage_key)
    if not path.is_file():
        raise ApiError(503, "file_unavailable", "Source file is temporarily unavailable")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=record.original_name,
        content_disposition_type="attachment" if download else "inline",
        headers={
            "Content-Security-Policy": "sandbox; default-src 'none'",
            "Cache-Control": "private, no-store",
        },
    )
