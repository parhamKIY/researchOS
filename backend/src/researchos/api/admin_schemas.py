import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from researchos.providers.contracts import GenerationParameters
from researchos.providers.safe_http import normalize_base_url

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


class SystemLLMWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    adapter: Literal["gemini", "openai_compatible", "mock"]
    base_url: str | None = Field(default=None, max_length=500)
    model_name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")
    api_key: SecretStr | None = Field(default=None, min_length=1, max_length=4096)
    parameters: GenerationParameters = Field(default_factory=GenerationParameters)

    @model_validator(mode="after")
    def validate_endpoint(self):
        if self.api_key is not None and not all(
            33 <= ord(char) <= 126 for char in self.api_key.get_secret_value()
        ):
            raise ValueError("API key must contain visible ASCII characters")
        if self.adapter == "mock":
            if self.base_url is not None or self.api_key is not None:
                raise ValueError("Mock configuration has no external endpoint or credential")
        else:
            self.base_url = normalize_base_url(
                self.base_url or (GEMINI_BASE if self.adapter == "gemini" else "")
            )
            if self.adapter == "gemini" and (
                self.base_url != GEMINI_BASE
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}", self.model_name)
            ):
                raise ValueError("Gemini requires its official endpoint and model identifier")
        return self
