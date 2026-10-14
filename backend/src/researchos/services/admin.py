import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from researchos.api.errors import ApiError
from researchos.domain.models import AuthSession, Paper, Project, User
from researchos.services.resources import etag, require_revision


def require_admin(db: Session, user_id: uuid.UUID, *, lock=False):
    query = select(User).where(
        User.id == user_id, User.is_active.is_(True), User.is_admin.is_(True)
    )
    if lock:
        query = query.with_for_update()
    user = db.scalar(query.execution_options(populate_existing=True))
    if user is None:
        raise ApiError(403, "admin_required", "Administrator access is required")
    return user


def user_read(user):
    return {
        "id": user.id,
        "email": user.email_normalized,
        "is_active": user.is_active,
        "is_admin": user.is_admin,
        "revision": user.revision,
        "etag": etag(user),
    }


def overview(db: Session):
    return {
        "users": db.scalar(select(func.count()).select_from(User)),
        "active_users": db.scalar(
            select(func.count()).select_from(User).where(User.is_active.is_(True))
        ),
        "projects": db.scalar(select(func.count()).select_from(Project)),
        "papers": db.scalar(select(func.count()).select_from(Paper)),
    }


def set_user_active(
    db: Session, admin_id: uuid.UUID, user_id: uuid.UUID, active: bool, revision: str | None
):
    require_admin(db, admin_id, lock=True)
    user = db.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None:
        raise ApiError(404, "user_missing", "Account was not found")
    require_revision(user, revision)
    if user.id == admin_id or user.is_admin:
        raise ApiError(
            409, "protected_account", "Administrator accounts must be managed through local setup"
        )
    if user.is_active != active:
        user.is_active = active
        user.revision += 1
        user.updated_at = datetime.now(UTC)
        if not active:
            db.execute(
                update(AuthSession)
                .where(AuthSession.owner_id == user_id, AuthSession.revoked_at.is_(None))
                .values(revoked_at=datetime.now(UTC))
            )
    db.commit()
    return user_read(user)
