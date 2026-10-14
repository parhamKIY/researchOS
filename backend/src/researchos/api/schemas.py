import uuid
from datetime import datetime

from pydantic import BaseModel


class UserRead(BaseModel):
    id: uuid.UUID
    email: str
    is_admin: bool


class SessionRead(BaseModel):
    user: UserRead
    expires_at: datetime
    csrf_token: str
