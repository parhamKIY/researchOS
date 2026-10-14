import hmac
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from researchos.api.errors import ApiError
from researchos.core.security import csrf_token, token_hash
from researchos.domain.models import AuthSession, User


def get_db(request: Request):
    with Session(request.app.state.engine) as db:
        yield db


Database = Annotated[Session, Depends(get_db)]


def trusted_origin(request: Request):
    expected = str(request.app.state.settings.public_origin).rstrip("/")
    if request.headers.get("origin") != expected:
        raise ApiError(403, "untrusted_origin", "Request origin is not allowed")


@dataclass
class Identity:
    user: User
    session: AuthSession
    token: str


def current_identity(request: Request, db: Database) -> Identity:
    token = request.cookies.get("researchos_session", "")
    if not 20 <= len(token) <= 128:
        raise ApiError(401, "unauthenticated", "Sign in to continue")
    row = db.execute(
        select(AuthSession, User)
        .join(User, User.id == AuthSession.owner_id)
        .where(
            AuthSession.token_hash == token_hash(token),
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > datetime.now(UTC),
            User.is_active.is_(True),
        )
    ).first()
    if row is None:
        raise ApiError(401, "unauthenticated", "Sign in to continue")
    return Identity(user=row[1], session=row[0], token=token)


Authenticated = Annotated[Identity, Depends(current_identity)]


def mutation_identity(request: Request, identity: Authenticated) -> Identity:
    trusted_origin(request)
    supplied = request.headers.get("x-csrf-token", "")
    expected = csrf_token(
        identity.token, request.app.state.settings.session_secret.get_secret_value()
    )
    if not hmac.compare_digest(supplied.encode(), expected.encode()) or not hmac.compare_digest(
        token_hash(supplied), identity.session.csrf_token_hash
    ):
        raise ApiError(403, "invalid_csrf", "Request verification failed")
    return identity


Mutation = Annotated[Identity, Depends(mutation_identity)]


def admin_identity(identity: Authenticated) -> Identity:
    if not identity.user.is_admin:
        raise ApiError(403, "admin_required", "Administrator access is required")
    return identity


def admin_mutation(identity: Mutation) -> Identity:
    return admin_identity(identity)


Administrator = Annotated[Identity, Depends(admin_identity)]
AdminMutation = Annotated[Identity, Depends(admin_mutation)]
