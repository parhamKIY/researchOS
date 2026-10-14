"""Resolve text targets without silently overriding a user's explicit private route."""

from dataclasses import dataclass, field

from pydantic import SecretStr
from sqlalchemy import select

from researchos.api.errors import ApiError
from researchos.core.credentials import CredentialCipher, CredentialUnavailable
from researchos.domain.models import (
    ModelRoutingRule,
    SystemLLMSettings,
    SystemProviderCandidate,
    User,
)
from researchos.providers.contracts import GenerationParameters, TextProvider
from researchos.services.provider_testing import adapter_for
from researchos.services.providers import TASK_CAPABILITIES, resolve_route
from researchos.services.system_llm import candidate_key, system_adapter


@dataclass(frozen=True)
class TextTarget:
    source: str
    configuration_id: str
    model_name: str
    parameters: GenerationParameters
    adapter: TextProvider = field(repr=False)
    key: SecretStr | None = field(repr=False)


def resolve_text_targets(db, owner, task, settings) -> list[TextTarget]:
    if db.scalar(select(User.id).where(User.id == owner, User.is_active.is_(True))) is None:
        raise ApiError(401, "unauthenticated", "Sign in to continue")
    if TASK_CAPABILITIES.get(task) != "text":
        raise ApiError(409, "task_not_supported", "The system default supports text tasks only")
    if db.get(ModelRoutingRule, (owner, task)) is not None:
        targets = []
        for model, provider in resolve_route(db, owner, task):
            key = None
            if provider.adapter != "mock":
                master = settings.credential_encryption_key
                try:
                    key = SecretStr(
                        CredentialCipher(master.get_secret_value() if master else None).decrypt(
                            provider.encrypted_credential or "", owner, provider.id
                        )
                    )
                except CredentialUnavailable:
                    raise ApiError(
                        503, "credential_unavailable", "Saved credential is unavailable"
                    ) from None
            targets.append(
                TextTarget(
                    "personal",
                    str(model.id),
                    model.model_name,
                    GenerationParameters.model_validate(model.parameters),
                    adapter_for(provider.adapter),
                    key,
                )
            )
        return targets
    active = db.scalar(
        select(SystemProviderCandidate)
        .join(
            SystemLLMSettings, SystemLLMSettings.active_candidate_id == SystemProviderCandidate.id
        )
        .where(SystemLLMSettings.id == 1, SystemProviderCandidate.state == "applied")
    )
    if active is None:
        raise ApiError(
            409,
            "routing_missing",
            "No system default is active; configure a personal model or contact an administrator",
        )
    return [
        TextTarget(
            "system",
            str(active.id),
            active.model_name,
            GenerationParameters.model_validate(active.parameters),
            system_adapter(active),
            candidate_key(active, settings),
        )
    ]
