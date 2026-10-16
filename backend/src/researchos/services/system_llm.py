import asyncio
import time
import uuid
from datetime import UTC, datetime, timedelta

from pydantic import SecretStr
from sqlalchemy import func, select

from researchos.api.errors import ApiError
from researchos.core.credentials import CredentialUnavailable, SystemCredentialCipher
from researchos.domain.models import AuthSession, SystemLLMSettings, SystemProviderCandidate
from researchos.providers.catalog import ERROR_MESSAGES, discover_models
from researchos.providers.compatible import CompatibleProvider
from researchos.providers.contracts import GenerationParameters, ProviderFailure, TextRequest
from researchos.providers.gemini import GeminiProvider
from researchos.providers.mock import MockProvider
from researchos.services.admin import require_admin
from researchos.services.resources import etag, require_revision

SYSTEM_CONTEXT = uuid.UUID(int=0)
SAFE_ERRORS = {
    "credential_unavailable",
    "model_unavailable",
    "provider_request_rejected",
    "provider_authentication_failed",
    "provider_access_denied",
    "provider_rate_limited",
    "provider_unavailable",
    "provider_response_too_large",
    "provider_connection_failed",
    "provider_outcome_unknown",
    "provider_content_blocked",
    "provider_empty_response",
    "provider_invalid_response",
    "provider_address_rejected",
    "provider_dns_failed",
}


def system_settings(db, *, lock=False):
    query = select(SystemLLMSettings).where(SystemLLMSettings.id == 1)
    if lock:
        query = query.with_for_update()
    row = db.scalar(query.execution_options(populate_existing=True))
    if row is None:
        raise ApiError(503, "system_settings_unavailable", "System settings are unavailable")
    return row


def candidate_read(row, *, admin=False):
    if row is None:
        return None
    keys = ["id", "adapter", "model_name", "parameters", "state", "execution_mode", "checked_at"]
    if admin:
        keys += [
            "base_url",
            "error_code",
            "outcome_unknown",
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "latency_ms",
            "created_at",
        ]
    result = {key: getattr(row, key) for key in keys}
    if admin:
        result["credential_configured"] = row.encrypted_credential is not None
    return result


def settings_read(db, *, admin=False):
    row = system_settings(db)
    active = (
        db.get(SystemProviderCandidate, row.active_candidate_id)
        if row.active_candidate_id
        else None
    )
    result = {
        "revision": row.revision,
        "etag": etag(row),
        "active": candidate_read(active, admin=admin),
        "updated_at": row.updated_at,
    }
    if admin:
        recent = db.scalars(
            select(SystemProviderCandidate)
            .order_by(SystemProviderCandidate.created_at.desc(), SystemProviderCandidate.id.desc())
            .limit(20)
        )
        result["checks"] = [candidate_read(item, admin=True) for item in recent]
    return result


def system_cipher(settings):
    master_key = settings.credential_encryption_key
    return SystemCredentialCipher(master_key.get_secret_value() if master_key else None)


def candidate_key(row, settings):
    if row.adapter == "mock":
        return None
    try:
        return SecretStr(
            system_cipher(settings).decrypt(row.encrypted_credential or "", SYSTEM_CONTEXT, row.id)
        )
    except CredentialUnavailable:
        raise ApiError(
            503,
            "credential_unavailable",
            "Saved credential is unavailable; check server encryption configuration",
        ) from None


def system_adapter(row):
    if row.adapter == "gemini":
        return GeminiProvider()
    if row.adapter == "openai_compatible":
        return CompatibleProvider(row.base_url)
    if row.adapter == "mock":
        return MockProvider()
    raise ProviderFailure("provider_unsupported")


def check_admin_session(db, admin_id, session_id):
    if session_id is None:
        return
    session = db.scalar(
        select(AuthSession.id).where(
            AuthSession.id == session_id,
            AuthSession.owner_id == admin_id,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > datetime.now(UTC),
        )
    )
    if session is None:
        raise ApiError(401, "unauthenticated", "Sign in to continue")


def resolve_system_key(db, payload, settings):
    if payload.adapter == "mock" or payload.api_key is not None:
        return payload.api_key
    current = system_settings(db)
    active = (
        db.get(SystemProviderCandidate, current.active_candidate_id)
        if current.active_candidate_id
        else None
    )
    if active is None or active.adapter != payload.adapter or active.base_url != payload.base_url:
        raise ApiError(422, "credential_required", "Enter an API key for this provider endpoint")
    return candidate_key(active, settings)


async def list_system_models(
    db, admin_id, payload, settings, *, session_id=None, discover=discover_models
):
    require_admin(db, admin_id)
    check_admin_session(db, admin_id, session_id)
    key = resolve_system_key(db, payload, settings)
    db.commit()  # Do not hold a database transaction during provider I/O.
    try:
        result = await discover(payload.adapter, payload.base_url, key)
    except ProviderFailure as exc:
        code = exc.code if exc.code in ERROR_MESSAGES else "provider_unavailable"
        raise ApiError(502, code, ERROR_MESSAGES[code]) from None
    except Exception:
        raise ApiError(
            502, "provider_unavailable", ERROR_MESSAGES["provider_unavailable"]
        ) from None
    db.expire_all()
    require_admin(db, admin_id)
    check_admin_session(db, admin_id, session_id)
    return result


def recover_system_probes(db):
    """Erase keys from abandoned probes without touching the active configuration."""
    now = datetime.now(UTC)
    active = (
        select(SystemLLMSettings.id)
        .where(SystemLLMSettings.active_candidate_id == SystemProviderCandidate.id)
        .exists()
    )
    rows = list(
        db.scalars(
            select(SystemProviderCandidate)
            .where(
                SystemProviderCandidate.state == "testing",
                SystemProviderCandidate.created_at < now - timedelta(minutes=5),
                ~active,
            )
            .order_by(SystemProviderCandidate.created_at)
            .limit(100)
            .with_for_update(skip_locked=True)
        )
    )
    for row in rows:
        row.state, row.error_code, row.encrypted_credential = "failed", "probe_interrupted", None
        row.outcome_unknown, row.checked_at = True, now
    db.commit()
    return len(rows)


async def verify_and_apply(
    db, admin_id, payload, match, settings, *, session_id=None, adapters=system_adapter
):
    require_admin(db, admin_id, lock=True)
    check_admin_session(db, admin_id, session_id)
    current = system_settings(db, lock=True)
    require_revision(current, match)
    count = db.scalar(
        select(func.count())
        .select_from(SystemProviderCandidate)
        .where(SystemProviderCandidate.created_at > datetime.now(UTC) - timedelta(minutes=1))
    )
    if count >= 10:
        raise ApiError(
            429,
            "provider_test_rate_limited",
            "Too many connection tests; wait one minute",
            {"Retry-After": "60"},
        )
    key = resolve_system_key(db, payload, settings)
    candidate = SystemProviderCandidate(
        id=uuid.uuid4(),
        created_by=admin_id,
        adapter=payload.adapter,
        base_url=payload.base_url,
        model_name=payload.model_name,
        parameters=payload.parameters.model_dump(exclude_none=True),
        execution_mode="mock" if payload.adapter == "mock" else "live",
    )
    if key is not None:
        try:
            candidate.encrypted_credential = system_cipher(settings).encrypt(
                key.get_secret_value(), SYSTEM_CONTEXT, candidate.id
            )
        except CredentialUnavailable:
            raise ApiError(
                503, "credential_unavailable", "Server credential encryption is unavailable"
            ) from None
    db.add(candidate)
    db.commit()  # Release locks before external I/O; the active pointer is unchanged.
    identifier = candidate.id
    parameters = GenerationParameters.model_validate(candidate.parameters)
    parameters.max_output_tokens = min(parameters.max_output_tokens or 256, 256)
    probe = TextRequest(
        model_name=candidate.model_name,
        prompt="Connectivity check. Reply with the word OK.",
        parameters=parameters,
    )
    started = time.monotonic()
    result, error = None, None
    try:
        async with asyncio.timeout(20):
            result = await adapters(candidate).generate_text(probe, key)
        if not result.text.strip() or result.execution_mode != candidate.execution_mode:
            raise ProviderFailure("provider_invalid_response", outcome_unknown=True)
    except ProviderFailure as exc:
        error = ProviderFailure(
            exc.code if exc.code in SAFE_ERRORS else "provider_unavailable",
            outcome_unknown=exc.outcome_unknown,
        )
    except Exception:
        error = ProviderFailure("provider_outcome_unknown", outcome_unknown=True)
    elapsed = max(0, int((time.monotonic() - started) * 1000))
    db.expire_all()
    candidate = db.get(SystemProviderCandidate, identifier)
    if candidate.state != "testing":
        error = ProviderFailure("probe_interrupted", outcome_unknown=True)
    candidate.checked_at = datetime.now(UTC)
    candidate.latency_ms = elapsed
    if result is not None and error is None:
        candidate.input_tokens = result.usage.input_tokens
        candidate.output_tokens = result.usage.output_tokens
        candidate.total_tokens = result.usage.total_tokens
    try:
        require_admin(db, admin_id, lock=True)
        check_admin_session(db, admin_id, session_id)
    except ApiError:
        candidate.state, candidate.error_code, candidate.encrypted_credential = (
            "failed",
            "admin_access_changed",
            None,
        )
        db.commit()
        raise
    current = system_settings(db, lock=True)
    if error is not None:
        candidate.state, candidate.error_code = "failed", error.code
        candidate.outcome_unknown = error.outcome_unknown
        candidate.encrypted_credential = None
        db.commit()
        return {
            "applied": False,
            "check": candidate_read(candidate, admin=True),
            "settings": settings_read(db, admin=True),
        }
    if etag(current) != match:
        candidate.state, candidate.error_code, candidate.encrypted_credential = (
            "stale",
            "stale_revision",
            None,
        )
        db.commit()
        raise ApiError(
            412, "stale_revision", "System settings changed during the test. Reload and test again"
        )
    if current.active_candidate_id:
        previous = db.get(SystemProviderCandidate, current.active_candidate_id)
        previous.state, previous.encrypted_credential = "superseded", None
    candidate.state = "applied"
    current.active_candidate_id = candidate.id
    current.revision += 1
    current.updated_at = datetime.now(UTC)
    db.commit()
    return {
        "applied": True,
        "check": candidate_read(candidate, admin=True),
        "settings": settings_read(db, admin=True),
    }
