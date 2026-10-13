from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from redis.exceptions import RedisError

from researchos.api.dependencies import Authenticated, Database, Mutation, trusted_origin
from researchos.api.errors import ApiError
from researchos.api.schemas import SessionRead
from researchos.core.security import csrf_token, token_hash
from researchos.services.auth import sign_in

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(max_length=320)
    password: SecretStr = Field(min_length=1, max_length=256)


def login_limit(request: Request):
    # The global bucket cannot be bypassed by rotating accounts or forwarded IP headers.
    try:
        count = request.app.state.broker.eval(
            "local n=redis.call('INCR',KEYS[1]); "
            "if n==1 then redis.call('EXPIRE',KEYS[1],60) end; return n",
            1,
            "researchos:login:global",
        )
    except RedisError:
        raise ApiError(503, "login_unavailable", "Sign in is temporarily unavailable") from None
    if count > 30:
        raise ApiError(429, "rate_limited", "Try again later", {"Retry-After": "60"})


def session_read(user, session, token: str, request: Request):
    return {
        "user": {"id": str(user.id), "email": user.email_normalized},
        "expires_at": session.expires_at.isoformat(),
        "csrf_token": csrf_token(
            token, request.app.state.settings.session_secret.get_secret_value()
        ),
    }


@router.post(
    "/login",
    response_model=SessionRead,
    dependencies=[Depends(trusted_origin), Depends(login_limit)],
)
def login(payload: LoginRequest, request: Request, response: Response, db: Database):
    if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
        raise ApiError(415, "json_required", "Sign in requires JSON")
    user, session, token = sign_in(
        db, request.app.state.settings, payload.email, payload.password.get_secret_value()
    )
    previous = request.cookies.get("researchos_session")
    if previous:
        from sqlalchemy import update

        from researchos.domain.models import AuthSession

        db.execute(
            update(AuthSession)
            .where(AuthSession.token_hash == token_hash(previous))
            .values(revoked_at=datetime.now(UTC))
        )
        db.commit()
    response.set_cookie(
        "researchos_session",
        token,
        httponly=True,
        samesite="lax",
        path="/",
        secure=request.app.state.settings.public_origin.scheme == "https",
        max_age=request.app.state.settings.session_lifetime_hours * 3600,
    )
    return session_read(user, session, token, request)


@router.get("/session", response_model=SessionRead)
def read_session(request: Request, identity: Authenticated):
    return session_read(identity.user, identity.session, identity.token, request)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: Database, identity: Mutation):
    identity.session.revoked_at = datetime.now(UTC)
    db.commit()
    response.delete_cookie(
        "researchos_session",
        path="/",
        httponly=True,
        samesite="lax",
        secure=request.app.state.settings.public_origin.scheme == "https",
    )
