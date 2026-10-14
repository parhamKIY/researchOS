import asyncio
import time
import uuid
from datetime import UTC, datetime, timedelta

from pydantic import SecretStr
from sqlalchemy import func, select

from researchos.api.errors import ApiError
from researchos.core.credentials import CredentialCipher, CredentialUnavailable
from researchos.domain.models import AIUsageRecord
from researchos.providers.contracts import GenerationParameters, ProviderFailure, TextRequest
from researchos.providers.gemini import GeminiProvider
from researchos.providers.mock import MockProvider
from researchos.services.providers import lock_owner, usable_model


def adapter_for(name):
    return GeminiProvider() if name == "gemini" else MockProvider()


async def test_connection(db, owner, provider_id, model_id, settings, adapters=adapter_for):
    lock_owner(db, owner)
    model, provider = usable_model(db, owner, model_id, "text")
    if provider.id != provider_id:
        raise ApiError(404, "model_not_found", "Model configuration was not found")
    key = None
    if provider.adapter == "gemini":
        cipher_key = settings.credential_encryption_key
        try:
            key = SecretStr(
                CredentialCipher(cipher_key.get_secret_value() if cipher_key else None).decrypt(
                    provider.encrypted_credential, owner, provider.id
                )
            )
        except CredentialUnavailable:
            raise ApiError(
                503,
                "credential_unavailable",
                "Saved credential cannot be read; check server encryption configuration",
            ) from None
    count = db.scalar(
        select(func.count())
        .select_from(AIUsageRecord)
        .where(
            AIUsageRecord.owner_id == owner,
            AIUsageRecord.task == "connection_test",
            AIUsageRecord.created_at > datetime.now(UTC) - timedelta(minutes=1),
        )
    )
    if count >= 10:
        raise ApiError(
            429,
            "provider_test_rate_limited",
            "Too many connection tests; wait one minute",
            headers={"Retry-After": "60"},
        )
    snapshot = (provider.revision, model.revision)
    # Fixed synthetic input: never read a paper during connectivity testing.
    parameters = GenerationParameters.model_validate(model.parameters)
    parameters.max_output_tokens = min(parameters.max_output_tokens or 256, 256)
    request = TextRequest(
        model_name=model.model_name,
        prompt="Connectivity check. Reply with the word OK.",
        parameters=parameters,
    )
    adapter = adapters(provider.adapter)
    result = None
    error = None
    usage_ids = []
    for attempt in [1, 2]:
        lock_owner(db, owner)
        db.expire_all()
        model, provider = usable_model(db, owner, model_id, "text")
        if snapshot != (provider.revision, model.revision):
            raise ApiError(409, "configuration_changed", "Configuration changed; reload it")
        usage = AIUsageRecord(
            id=uuid.uuid4(),
            owner_id=owner,
            provider_id=provider.id,
            model_configuration_id=model.id,
            provider_name=provider.display_name,
            model_name=model.model_name,
            execution_mode="mock" if provider.adapter == "mock" else "live",
            task="connection_test",
            attempt=attempt,
            state="started",
        )
        db.add(usage)
        db.commit()
        usage_ids.append(str(usage.id))
        started = time.monotonic()
        try:
            result = await adapter.generate_text(request, key)
        except ProviderFailure as failure:
            error = failure
        except Exception:
            error = ProviderFailure("provider_outcome_unknown", outcome_unknown=True)
        usage.latency_ms = round((time.monotonic() - started) * 1000)
        if result:
            usage.state = "completed"
            for name in ["input_tokens", "output_tokens", "thought_tokens", "total_tokens"]:
                setattr(usage, name, getattr(result.usage, name))
            if result.execution_mode == "mock":
                usage.cost_amount, usage.currency, usage.cost_source = 0, "USD", "mock_no_charge"
        else:
            usage.state = "outcome_unknown" if error.outcome_unknown else "failed"
            usage.error_code = error.code
        db.commit()
        db.expire_all()
        current_model, current_provider = usable_model(db, owner, model_id, "text")
        if snapshot != (current_provider.revision, current_model.revision):
            raise ApiError(
                409, "configuration_changed", "Configuration changed during the test; reload it"
            )
        if result or not error.retryable or attempt == 2:
            break
        await asyncio.sleep(0.5)
    return {
        "status": "ok" if result else "failed",
        "execution_mode": "mock" if provider.adapter == "mock" else "live",
        "code": "mock_connection_ok"
        if result and result.execution_mode == "mock"
        else "connection_ok"
        if result
        else error.code,
        "checked_at": datetime.now(UTC),
        "usage_ids": usage_ids,
        "outcome_unknown": error.outcome_unknown if not result else False,
    }
