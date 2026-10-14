import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Header, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from sqlalchemy import select

from researchos.api.dependencies import Authenticated, Database, Mutation
from researchos.domain.models import AIUsageRecord, ModelConfiguration, ProviderConnection
from researchos.providers.contracts import GenerationParameters
from researchos.services.provider_testing import test_connection
from researchos.services.providers import (
    create_model,
    create_provider,
    model_read,
    owned_model,
    owned_provider,
    patch_model,
    patch_provider,
    provider_read,
    put_routing,
    routing_read,
)
from researchos.services.resources import cursor_filter, cursor_scope, encode_cursor, etag

router = APIRouter(prefix="/api/v1", tags=["AI provider settings"])
Capability = Literal["text", "vision", "embeddings"]
Task = Literal[
    "paper_summary", "methodology", "research_gaps", "paper_chat", "figure_analysis", "embeddings"
]


class StrictPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class ProviderCreate(StrictPayload):
    adapter: Literal["gemini", "mock"]
    display_name: str = Field(min_length=1, max_length=100)
    api_key: SecretStr | None = Field(default=None, min_length=10, max_length=512)

    @field_validator("display_name")
    @classmethod
    def name(cls, value):
        if value is not None and not value.strip():
            raise ValueError("Name cannot be blank")
        return value.strip() if value else value

    @field_validator("api_key")
    @classmethod
    def safe_key(cls, value):
        if value and any(not 33 <= ord(char) <= 126 for char in value.get_secret_value()):
            raise ValueError("Key must contain printable characters without spaces")
        return value

    @model_validator(mode="after")
    def credential_policy(self):
        if (self.adapter == "gemini") != (self.api_key is not None):
            raise ValueError("Gemini requires a key; mock does not accept one")
        return self


class ProviderPatch(StrictPayload):
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    api_key: SecretStr | None = Field(default=None, min_length=10, max_length=512)
    clear_credential: bool = False
    enabled: bool | None = None
    name = field_validator("display_name")(ProviderCreate.name.__func__)
    safe_key = field_validator("api_key")(ProviderCreate.safe_key.__func__)

    @model_validator(mode="after")
    def valid_changes(self):
        if not self.model_fields_set or any(
            getattr(self, key) is None for key in self.model_fields_set
        ):
            raise ValueError("Provide non-null changes")
        if self.api_key and self.clear_credential:
            raise ValueError("Replace or clear a key, not both")
        return self


class ProviderRead(BaseModel):
    id: uuid.UUID
    adapter: Literal["gemini", "mock"]
    display_name: str
    credential_configured: bool
    credential_display: str | None
    enabled: bool
    revision: int
    created_at: datetime
    updated_at: datetime


class ProviderList(BaseModel):
    items: list[ProviderRead]
    next_cursor: str | None


class ModelCreate(StrictPayload):
    model_name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
    capabilities: list[Capability] = Field(min_length=1, max_length=3)
    parameters: GenerationParameters = Field(default_factory=GenerationParameters)

    @field_validator("capabilities")
    @classmethod
    def unique(cls, value):
        if value is not None and len(set(value)) != len(value):
            raise ValueError("Duplicate capabilities")
        return value


class ModelPatch(StrictPayload):
    model_name: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
    capabilities: list[Capability] | None = Field(default=None, min_length=1, max_length=3)
    parameters: GenerationParameters | None = None
    enabled: bool | None = None
    unique = field_validator("capabilities")(ModelCreate.unique.__func__)

    @model_validator(mode="after")
    def nonempty(self):
        if not self.model_fields_set or any(
            getattr(self, key) is None for key in self.model_fields_set
        ):
            raise ValueError("Provide non-null changes")
        return self


class ModelRead(BaseModel):
    id: uuid.UUID
    provider_id: uuid.UUID
    model_name: str
    capabilities: list[Capability]
    capability_source: Literal["manual"]
    parameters: GenerationParameters
    enabled: bool
    revision: int
    created_at: datetime
    updated_at: datetime


class ModelList(BaseModel):
    items: list[ModelRead]
    next_cursor: str | None


class RoutingRule(StrictPayload):
    task: Task
    primary_model_id: uuid.UUID
    fallback_model_id: uuid.UUID | None = None
    allowed_provider_ids: list[uuid.UUID] = Field(min_length=1, max_length=2)

    @model_validator(mode="after")
    def distinct(self):
        if self.primary_model_id == self.fallback_model_id or len(
            set(self.allowed_provider_ids)
        ) != len(self.allowed_provider_ids):
            raise ValueError("Duplicate routing choices")
        return self


class RoutingWrite(StrictPayload):
    rules: list[RoutingRule] = Field(max_length=6)

    @model_validator(mode="after")
    def distinct_tasks(self):
        if len({rule.task for rule in self.rules}) != len(self.rules):
            raise ValueError("Duplicate tasks")
        return self


class RoutingRead(RoutingWrite):
    revision: int
    updated_at: datetime


class ConnectionTest(StrictPayload):
    model_configuration_id: uuid.UUID


class ConnectionRead(BaseModel):
    status: Literal["ok", "failed"]
    code: str
    execution_mode: Literal["live", "mock"]
    checked_at: datetime
    usage_ids: list[uuid.UUID]
    outcome_unknown: bool


class UsageRead(BaseModel):
    id: uuid.UUID
    provider_id: uuid.UUID
    model_configuration_id: uuid.UUID
    provider_name: str
    model_name: str
    execution_mode: str
    task: str
    attempt: int
    state: str
    error_code: str | None
    input_tokens: int | None
    output_tokens: int | None
    thought_tokens: int | None
    total_tokens: int | None
    latency_ms: int | None
    cost_amount: float | None
    currency: str | None
    cost_source: str | None
    created_at: datetime


class UsageList(BaseModel):
    items: list[UsageRead]
    next_cursor: str | None


def page_rows(request, db, owner, model, query, kind, filters, limit, cursor):
    scope = cursor_scope(owner, kind, {**filters, "limit": limit})
    secret = request.app.state.settings.session_secret.get_secret_value()
    if cursor:
        query = query.where(cursor_filter(model, cursor, scope, secret))
    rows = list(
        db.scalars(query.order_by(model.created_at.desc(), model.id.desc()).limit(limit + 1))
    )
    return rows[:limit], encode_cursor(rows[limit - 1], scope, secret) if len(
        rows
    ) > limit else None


@router.post("/providers", response_model=ProviderRead, status_code=201)
def add_provider(
    payload: ProviderCreate, request: Request, response: Response, db: Database, identity: Mutation
):
    row = create_provider(db, identity.user.id, payload, request.app.state.settings)
    response.headers.update({"ETag": etag(row), "Location": f"/api/v1/providers/{row.id}"})
    return provider_read(row)


@router.get("/providers", response_model=ProviderList)
def providers(
    request: Request,
    db: Database,
    identity: Authenticated,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
):
    rows, next_cursor = page_rows(
        request,
        db,
        identity.user.id,
        ProviderConnection,
        select(ProviderConnection).where(
            ProviderConnection.owner_id == identity.user.id, ProviderConnection.deleted_at.is_(None)
        ),
        "providers",
        {},
        limit,
        cursor,
    )
    return {"items": [provider_read(row) for row in rows], "next_cursor": next_cursor}


@router.get("/providers/{provider_id}", response_model=ProviderRead)
def provider(provider_id: uuid.UUID, response: Response, db: Database, identity: Authenticated):
    row = owned_provider(db, identity.user.id, provider_id)
    response.headers["ETag"] = etag(row)
    return provider_read(row)


@router.patch("/providers/{provider_id}", response_model=ProviderRead)
def change_provider(
    provider_id: uuid.UUID,
    payload: ProviderPatch,
    request: Request,
    response: Response,
    db: Database,
    identity: Mutation,
    if_match: Annotated[str | None, Header()] = None,
):
    row = patch_provider(
        db, identity.user.id, provider_id, payload, if_match, request.app.state.settings
    )
    response.headers["ETag"] = etag(row)
    return provider_read(row)


@router.delete("/providers/{provider_id}", status_code=204)
def remove_provider(
    provider_id: uuid.UUID,
    request: Request,
    db: Database,
    identity: Mutation,
    if_match: Annotated[str | None, Header()] = None,
):
    patch_provider(
        db, identity.user.id, provider_id, None, if_match, request.app.state.settings, remove=True
    )


@router.post("/providers/{provider_id}/models", response_model=ModelRead, status_code=201)
def add_model(
    provider_id: uuid.UUID,
    payload: ModelCreate,
    response: Response,
    db: Database,
    identity: Mutation,
):
    row = create_model(db, identity.user.id, provider_id, payload)
    response.headers.update({"ETag": etag(row), "Location": f"/api/v1/models/{row.id}"})
    return model_read(row)


@router.get("/providers/{provider_id}/models", response_model=ModelList)
def models(
    provider_id: uuid.UUID,
    request: Request,
    db: Database,
    identity: Authenticated,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
):
    owned_provider(db, identity.user.id, provider_id)
    rows, next_cursor = page_rows(
        request,
        db,
        identity.user.id,
        ModelConfiguration,
        select(ModelConfiguration).where(
            ModelConfiguration.owner_id == identity.user.id,
            ModelConfiguration.provider_id == provider_id,
        ),
        "models",
        {"provider_id": str(provider_id)},
        limit,
        cursor,
    )
    return {"items": [model_read(row) for row in rows], "next_cursor": next_cursor}


@router.get("/models/{model_id}", response_model=ModelRead)
def model(model_id: uuid.UUID, response: Response, db: Database, identity: Authenticated):
    row = owned_model(db, identity.user.id, model_id)
    response.headers["ETag"] = etag(row)
    return model_read(row)


@router.patch("/models/{model_id}", response_model=ModelRead)
def change_model(
    model_id: uuid.UUID,
    payload: ModelPatch,
    response: Response,
    db: Database,
    identity: Mutation,
    if_match: Annotated[str | None, Header()] = None,
):
    row = patch_model(db, identity.user.id, model_id, payload, if_match)
    response.headers["ETag"] = etag(row)
    return model_read(row)


@router.delete("/models/{model_id}", status_code=204)
def remove_model(
    model_id: uuid.UUID,
    db: Database,
    identity: Mutation,
    if_match: Annotated[str | None, Header()] = None,
):
    patch_model(db, identity.user.id, model_id, None, if_match, remove=True)


@router.get("/settings/model-routing", response_model=RoutingRead)
def routing(response: Response, db: Database, identity: Authenticated):
    settings, result = routing_read(db, identity.user.id)
    response.headers["ETag"] = etag(settings)
    return result


@router.put("/settings/model-routing", response_model=RoutingRead)
def routing_update(
    payload: RoutingWrite,
    response: Response,
    db: Database,
    identity: Mutation,
    if_match: Annotated[str | None, Header()] = None,
):
    settings, result = put_routing(db, identity.user.id, payload, if_match)
    response.headers["ETag"] = etag(settings)
    return result


@router.post("/providers/{provider_id}/test", response_model=ConnectionRead)
async def connection(
    provider_id: uuid.UUID,
    payload: ConnectionTest,
    request: Request,
    db: Database,
    identity: Mutation,
):
    owned_provider(db, identity.user.id, provider_id)
    return await test_connection(
        db,
        identity.user.id,
        provider_id,
        payload.model_configuration_id,
        request.app.state.settings,
    )


@router.get("/analytics/usage", response_model=UsageList)
def usage(
    request: Request,
    db: Database,
    identity: Authenticated,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
):
    rows, next_cursor = page_rows(
        request,
        db,
        identity.user.id,
        AIUsageRecord,
        select(AIUsageRecord).where(AIUsageRecord.owner_id == identity.user.id),
        "usage",
        {},
        limit,
        cursor,
    )
    return {
        "items": [{key: getattr(row, key) for key in UsageRead.model_fields} for row in rows],
        "next_cursor": next_cursor,
    }
