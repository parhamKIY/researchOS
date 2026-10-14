import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from researchos.api.errors import ApiError
from researchos.core.credentials import CredentialCipher, CredentialUnavailable
from researchos.domain.models import (
    ModelConfiguration,
    ModelRoutingRule,
    ModelRoutingSettings,
    ProviderConnection,
    User,
)
from researchos.providers.contracts import GenerationParameters
from researchos.services.resources import require_revision

TASK_CAPABILITIES = {
    "paper_summary": "text",
    "methodology": "text",
    "research_gaps": "text",
    "paper_chat": "text",
    "figure_analysis": "vision",
    "embeddings": "embeddings",
}


def lock_owner(db, owner):
    active = db.scalar(
        select(User.id).where(User.id == owner, User.is_active.is_(True)).with_for_update()
    )
    if active is None:
        raise ApiError(401, "unauthenticated", "Sign in to continue")


def owned_provider(db, owner, identifier, lock=False):
    query = select(ProviderConnection).where(
        ProviderConnection.owner_id == owner,
        ProviderConnection.id == identifier,
        ProviderConnection.deleted_at.is_(None),
    )
    row = db.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise ApiError(404, "provider_not_found", "Provider was not found")
    return row


def owned_model(db, owner, identifier, lock=False):
    query = (
        select(ModelConfiguration)
        .join(ProviderConnection, ProviderConnection.id == ModelConfiguration.provider_id)
        .where(
            ModelConfiguration.owner_id == owner,
            ModelConfiguration.id == identifier,
            ProviderConnection.deleted_at.is_(None),
        )
    )
    row = db.scalar(query.with_for_update(of=ModelConfiguration) if lock else query)
    if row is None:
        raise ApiError(404, "model_not_found", "Model configuration was not found")
    return row


def provider_read(row):
    return {
        **{
            key: getattr(row, key)
            for key in [
                "id",
                "adapter",
                "display_name",
                "enabled",
                "revision",
                "created_at",
                "updated_at",
            ]
        },
        "credential_configured": row.encrypted_credential is not None,
        "credential_display": "Stored securely" if row.encrypted_credential else None,
    }


def model_read(row):
    return {
        key: getattr(row, key)
        for key in [
            "id",
            "provider_id",
            "model_name",
            "capabilities",
            "capability_source",
            "parameters",
            "enabled",
            "revision",
            "created_at",
            "updated_at",
        ]
    }


def encrypt_key(settings, value, owner, provider_id):
    key = settings.credential_encryption_key
    try:
        return CredentialCipher(key.get_secret_value() if key else None).encrypt(
            value.get_secret_value(), owner, provider_id
        )
    except CredentialUnavailable:
        raise ApiError(
            503, "credential_storage_unavailable", "Credential encryption is not available"
        ) from None


def create_provider(db, owner, payload, settings):
    lock_owner(db, owner)
    row = ProviderConnection(
        id=uuid.uuid4(), owner_id=owner, adapter=payload.adapter, display_name=payload.display_name
    )
    if payload.api_key:
        row.encrypted_credential = encrypt_key(settings, payload.api_key, owner, row.id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def patch_provider(db, owner, identifier, payload, match, settings, remove=False):
    lock_owner(db, owner)
    row = owned_provider(db, owner, identifier, lock=True)
    require_revision(row, match)
    changes = payload.model_dump(exclude_unset=True) if payload else {}
    if row.adapter == "mock" and (changes.get("api_key") or changes.get("clear_credential")):
        raise ApiError(422, "mock_has_no_credential", "The mock provider does not use credentials")
    if changes.get("api_key"):
        row.encrypted_credential = encrypt_key(settings, changes["api_key"], owner, row.id)
        row.credential_revision += 1
    if changes.get("clear_credential") or remove:
        row.encrypted_credential = None
        row.credential_revision += 1
    for name in ["display_name", "enabled"]:
        if name in changes:
            setattr(row, name, changes[name])
    if remove:
        row.enabled = False
        row.deleted_at = datetime.now(UTC)
    row.revision += 1
    row.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(row)
    return row


def create_model(db, owner, provider_id, payload):
    lock_owner(db, owner)
    owned_provider(db, owner, provider_id)
    row = ModelConfiguration(
        owner_id=owner,
        provider_id=provider_id,
        model_name=payload.model_name,
        capabilities=sorted(payload.capabilities),
        parameters=payload.parameters.model_dump(exclude_none=True),
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ApiError(
            409, "model_exists", "This model is already configured for the provider"
        ) from None
    db.refresh(row)
    return row


def patch_model(db, owner, identifier, payload, match, remove=False):
    lock_owner(db, owner)
    row = owned_model(db, owner, identifier, lock=True)
    require_revision(row, match)
    changes = payload.model_dump(exclude_unset=True) if payload else {"enabled": False}
    if "parameters" in changes:
        changes["parameters"] = GenerationParameters.model_validate(
            changes["parameters"]
        ).model_dump(exclude_none=True)
    for name, value in changes.items():
        setattr(row, name, sorted(value) if name == "capabilities" else value)
    row.revision += 1
    row.updated_at = datetime.now(UTC)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ApiError(
            409, "model_exists", "This model is already configured for the provider"
        ) from None
    db.refresh(row)
    return row


def usable_model(db, owner, identifier, capability):
    model = owned_model(db, owner, identifier)
    provider = owned_provider(db, owner, model.provider_id)
    if not model.enabled or not provider.enabled:
        raise ApiError(409, "configuration_disabled", "Provider or model is disabled")
    if provider.adapter == "gemini" and not provider.encrypted_credential:
        raise ApiError(
            409, "credential_missing", "Configure a provider key before using this model"
        )
    if capability not in model.capabilities:
        raise ApiError(
            422,
            "model_capability_mismatch",
            "Model does not have the required configured capability",
        )
    return model, provider


def routing_settings(db, owner):
    db.execute(insert(ModelRoutingSettings).values(owner_id=owner).on_conflict_do_nothing())
    db.commit()
    return db.get(ModelRoutingSettings, owner)


def routing_read(db, owner):
    settings = routing_settings(db, owner)
    rules = list(
        db.scalars(
            select(ModelRoutingRule)
            .where(ModelRoutingRule.owner_id == owner)
            .order_by(ModelRoutingRule.task)
        )
    )
    return settings, {
        "revision": settings.revision,
        "updated_at": settings.updated_at,
        "rules": [
            {
                key: getattr(row, key)
                for key in ["task", "primary_model_id", "fallback_model_id", "allowed_provider_ids"]
            }
            for row in rules
        ],
    }


def put_routing(db, owner, payload, match):
    routing_settings(db, owner)
    lock_owner(db, owner)
    settings = db.scalar(
        select(ModelRoutingSettings).where(ModelRoutingSettings.owner_id == owner).with_for_update()
    )
    require_revision(settings, match)
    for rule in payload.rules:
        expected = set()
        for identifier in [rule.primary_model_id, rule.fallback_model_id]:
            if identifier:
                model, provider = usable_model(db, owner, identifier, TASK_CAPABILITIES[rule.task])
                expected.add(provider.id)
        if expected != set(rule.allowed_provider_ids):
            raise ApiError(
                422,
                "provider_consent_mismatch",
                "Allowed providers must match the explicitly selected models",
            )
    db.execute(delete(ModelRoutingRule).where(ModelRoutingRule.owner_id == owner))
    for rule in payload.rules:
        db.add(
            ModelRoutingRule(
                owner_id=owner,
                task=rule.task,
                primary_model_id=rule.primary_model_id,
                fallback_model_id=rule.fallback_model_id,
                allowed_provider_ids=[str(value) for value in rule.allowed_provider_ids],
            )
        )
    settings.revision += 1
    settings.updated_at = datetime.now(UTC)
    db.commit()
    return routing_read(db, owner)


def resolve_route(db, owner, task):
    rule = db.get(ModelRoutingRule, (owner, task))
    if rule is None:
        raise ApiError(409, "routing_missing", "Configure a model for this task")
    candidates = []
    for identifier in [rule.primary_model_id, rule.fallback_model_id]:
        if identifier:
            model, provider = usable_model(db, owner, identifier, TASK_CAPABILITIES[task])
            if str(provider.id) not in rule.allowed_provider_ids:
                raise ApiError(
                    403, "provider_not_allowed", "Provider is outside the configured route"
                )
            candidates.append((model, provider))
    return candidates
