import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Query, Request
from pydantic import BaseModel, ConfigDict, StrictBool
from redis.exceptions import RedisError
from sqlalchemy import select

from researchos.api.admin_schemas import SystemLLMWrite, SystemProviderWrite
from researchos.api.dependencies import Administrator, AdminMutation, Database
from researchos.api.errors import ApiError
from researchos.api.providers import page_rows
from researchos.domain.models import User
from researchos.services.admin import overview, set_user_active, user_read
from researchos.services.system_llm import list_system_models, settings_read, verify_and_apply

router = APIRouter(prefix="/api/v1/admin", tags=["Administration"])


class UserStatusWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_active: StrictBool


@router.get("/overview")
def admin_overview(db: Database, identity: Administrator):
    return overview(db)


@router.get("/llm")
def llm_settings(db: Database, identity: Administrator):
    return settings_read(db, admin=True)


@router.post("/llm/verify-and-apply")
async def llm_update(
    payload: SystemLLMWrite,
    request: Request,
    db: Database,
    identity: AdminMutation,
    if_match: Annotated[str | None, Header()] = None,
):
    return await verify_and_apply(
        db,
        identity.user.id,
        payload,
        if_match,
        request.app.state.settings,
        session_id=identity.session.id,
    )


@router.post("/llm/models")
async def llm_models(
    payload: SystemProviderWrite, request: Request, db: Database, identity: AdminMutation
):
    try:
        count = request.app.state.broker.eval(
            "local n=redis.call('INCR',KEYS[1]); "
            "if n==1 then redis.call('EXPIRE',KEYS[1],60) end; return n",
            1,
            f"researchos:model-catalog:{identity.user.id}",
        )
    except RedisError:
        raise ApiError(
            503, "catalog_unavailable", "Model listing is temporarily unavailable"
        ) from None
    if count > 10:
        raise ApiError(
            429,
            "catalog_rate_limited",
            "Too many model list requests; wait one minute",
            {"Retry-After": "60"},
        )
    return await list_system_models(
        db, identity.user.id, payload, request.app.state.settings, session_id=identity.session.id
    )


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
