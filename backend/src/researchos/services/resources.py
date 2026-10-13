import base64
import hashlib
import hmac
import json
import uuid
from datetime import datetime

from sqlalchemy import tuple_

from researchos.api.errors import ApiError


def etag(resource) -> str:
    return f'"{resource.id}:{resource.revision}"'


def require_revision(resource, supplied: str | None):
    if supplied is None:
        raise ApiError(428, "revision_required", "Reload the resource before changing it")
    if supplied != etag(resource):
        raise ApiError(412, "stale_revision", "This resource changed. Reload it and try again")


def cursor_scope(owner_id: uuid.UUID, kind: str, filters: dict) -> str:
    return json.dumps([str(owner_id), kind, filters], sort_keys=True, separators=(",", ":"))


def encode_cursor(resource, scope: str, secret: str) -> str:
    data = json.dumps([scope, resource.created_at.isoformat(), str(resource.id)]).encode()
    payload = base64.urlsafe_b64encode(data).decode().rstrip("=")
    signature = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def cursor_filter(model, cursor: str, scope: str, secret: str):
    try:
        payload, signature = cursor.split(".")
        expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature.encode(), expected.encode()):
            raise ValueError
        stored_scope, date, identifier = json.loads(
            base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        )
        timestamp = datetime.fromisoformat(date)
        if stored_scope != scope or timestamp.tzinfo is None:
            raise ValueError
        return tuple_(model.created_at, model.id) < tuple_(timestamp, uuid.UUID(identifier))
    except (ValueError, TypeError, KeyError):
        raise ApiError(
            422, "invalid_cursor", "Pagination cursor is invalid for this list"
        ) from None
