import uuid
from datetime import datetime

from pydantic import BaseModel


class UserRead(BaseModel):
    id: uuid.UUID
    email: str


class SessionRead(BaseModel):
    user: UserRead
    expires_at: datetime
    csrf_token: str
