import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Query, Request
from pydantic import BaseModel, ConfigDict, StrictBool
from sqlalchemy import select

from researchos.api.dependencies import Administrator, AdminMutation, Database
from researchos.api.providers import page_rows
from researchos.domain.models import User
from researchos.services.admin import overview, set_user_active, user_read

router = APIRouter(prefix="/api/v1/admin", tags=["Administration"])


class UserStatusWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_active: StrictBool


@router.get("/overview")
def admin_overview(db: Database, identity: Administrator):
    return overview(db)


@router.get("/users")
def users(
    request: Request,
    db: Database,
    identity: Administrator,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
):
    rows, next_cursor = page_rows(
        request, db, identity.user.id, User, select(User), "admin_users", {}, limit, cursor
    )
    return {"items": [user_read(row) for row in rows], "next_cursor": next_cursor}


@router.patch("/users/{user_id}")
def user_status(
    user_id: uuid.UUID,
    payload: UserStatusWrite,
    db: Database,
    identity: AdminMutation,
    if_match: Annotated[str | None, Header()] = None,
):
    return set_user_active(db, identity.user.id, user_id, payload.is_active, if_match)
