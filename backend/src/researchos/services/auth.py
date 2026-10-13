import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from researchos.api.errors import ApiError
from researchos.core.config import Settings
from researchos.core.security import csrf_token, normalize_email, token_hash, verify_password
from researchos.domain.models import AuthSession, User


def sign_in(
    db: Session, settings: Settings, email: str, password: str
) -> tuple[User, AuthSession, str]:
    try:
        email = normalize_email(email)
    except ValueError:
        email = "invalid"
    user = db.scalar(select(User).where(User.email_normalized == email))
    valid = verify_password(user.password_hash if user else None, password)
    if not valid or user is None or not user.is_active:
        raise ApiError(401, "invalid_credentials", "Email or password is incorrect")
    token = secrets.token_urlsafe(32)
    session = AuthSession(
        owner_id=user.id,
        token_hash=token_hash(token),
        csrf_token_hash=token_hash(csrf_token(token, settings.session_secret.get_secret_value())),
        expires_at=datetime.now(UTC) + timedelta(hours=settings.session_lifetime_hours),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return user, session, token
