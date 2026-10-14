from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class GenerationParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    temperature: float | None = Field(default=None, ge=0, le=2, allow_inf_nan=False)
    max_output_tokens: int | None = Field(default=None, ge=16, le=8192, strict=True)


class TextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
    prompt: str = Field(min_length=1, max_length=50000, repr=False)
    parameters: GenerationParameters = Field(default_factory=GenerationParameters)


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    thought_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True)
class TextResponse:
    text: str
    usage: TokenUsage
    execution_mode: str


class ProviderFailure(Exception):
    def __init__(self, code: str, *, retryable=False, outcome_unknown=False):
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.outcome_unknown = outcome_unknown


class TextProvider(Protocol):
    async def generate_text(self, request: TextRequest, key: SecretStr | None) -> TextResponse: ...
