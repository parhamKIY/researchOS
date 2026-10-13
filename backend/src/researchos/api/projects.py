import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Header, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select

from researchos.api.dependencies import Authenticated, Database, Mutation
from researchos.domain.models import Project
from researchos.services.projects import (
    change_project,
    create_project,
    delete_project,
    owned_project,
)
from researchos.services.resources import cursor_filter, cursor_scope, encode_cursor, etag

router = APIRouter(prefix="/api/v1/projects", tags=["Projects"])


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)

    @field_validator("name")
    @classmethod
    def meaningful_name(cls, value):
        if not value.strip():
            raise ValueError("Project name cannot be blank")
        return value.strip()


class ProjectPatch(ProjectCreate):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    archived: bool | None = None

    @model_validator(mode="after")
    def nonempty(self):
        if not self.model_fields_set or any(
            getattr(self, key) is None for key in self.model_fields_set
        ):
            raise ValueError("Provide at least one non-null field")
        return self


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    description: str
    archived_at: datetime | None
    revision: int
    created_at: datetime
    updated_at: datetime


class ProjectList(BaseModel):
    items: list[ProjectRead]
    next_cursor: str | None


@router.post("", status_code=201, response_model=ProjectRead)
def create(payload: ProjectCreate, response: Response, db: Database, identity: Mutation):
    project = create_project(db, identity.user.id, payload.name, payload.description)
    response.headers["Location"] = f"/api/v1/projects/{project.id}"
    response.headers["ETag"] = etag(project)
    return project


@router.get("", response_model=ProjectList)
def listing(
    request: Request,
    db: Database,
    identity: Authenticated,
    archived: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
):
    secret = request.app.state.settings.session_secret.get_secret_value()
    scope = cursor_scope(identity.user.id, "projects", {"archived": archived, "limit": limit})
    query = select(Project).where(Project.owner_id == identity.user.id)
    query = query.where(
        Project.archived_at.is_not(None) if archived else Project.archived_at.is_(None)
    )
    if cursor:
        query = query.where(cursor_filter(Project, cursor, scope, secret))
    rows = list(
        db.scalars(query.order_by(Project.created_at.desc(), Project.id.desc()).limit(limit + 1))
    )
    return {
        "items": rows[:limit],
        "next_cursor": encode_cursor(rows[limit - 1], scope, secret) if len(rows) > limit else None,
    }


@router.get("/{project_id}", response_model=ProjectRead)
def read(project_id: uuid.UUID, response: Response, db: Database, identity: Authenticated):
    project = owned_project(db, identity.user.id, project_id)
    response.headers["ETag"] = etag(project)
    return project


@router.patch("/{project_id}", response_model=ProjectRead)
def patch(
    project_id: uuid.UUID,
    payload: ProjectPatch,
    response: Response,
    db: Database,
    identity: Mutation,
    if_match: Annotated[str | None, Header()] = None,
):
    project = change_project(
        db, identity.user.id, project_id, payload.model_dump(exclude_unset=True), if_match
    )
    response.headers["ETag"] = etag(project)
    return project


@router.delete("/{project_id}", status_code=204)
def remove(
    project_id: uuid.UUID,
    db: Database,
    identity: Mutation,
    if_match: Annotated[str | None, Header()] = None,
):
    delete_project(db, identity.user.id, project_id, if_match)
