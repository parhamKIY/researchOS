import asyncio
import json
import re

import httpx
from pydantic import SecretStr

from researchos.providers.contracts import ProviderFailure, TextRequest, TextResponse, TokenUsage

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models/"


class GeminiProvider:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        self._transport = transport

    async def generate_text(self, request: TextRequest, key: SecretStr | None) -> TextResponse:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}", request.model_name):
            raise ProviderFailure("model_unavailable")
        if key is None:
            raise ProviderFailure("credential_unavailable")
        config = {"maxOutputTokens": request.parameters.max_output_tokens or 1024}
        if request.parameters.temperature is not None:
            config["temperature"] = request.parameters.temperature
        payload = {
            "contents": [{"role": "user", "parts": [{"text": request.prompt}]}],
            "generationConfig": config,
        }
        try:
            async with (
                asyncio.timeout(15),
                httpx.AsyncClient(
                    timeout=httpx.Timeout(10, connect=5),
                    follow_redirects=False,
                    trust_env=False,
                    transport=self._transport,
                ) as client,
            ):
                async with client.stream(
                    "POST",
                    f"{BASE_URL}{request.model_name}:generateContent",
                    headers={"x-goog-api-key": key.get_secret_value()},
                    json=payload,
                ) as response:
                    if response.status_code != 200:
                        codes = {
                            400: "provider_request_rejected",
                            401: "provider_authentication_failed",
                            403: "provider_access_denied",
                            404: "model_unavailable",
                            429: "provider_rate_limited",
                        }
                        raise ProviderFailure(
                            codes.get(response.status_code, "provider_unavailable"),
                            retryable=response.status_code == 429,
                            outcome_unknown=response.status_code >= 500,
                        )
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(body) + len(chunk) > 2 * 1024 * 1024:
                            raise ProviderFailure(
                                "provider_response_too_large", outcome_unknown=True
                            )
                        body.extend(chunk)
        except (httpx.ConnectError, httpx.ConnectTimeout):
            raise ProviderFailure("provider_connection_failed", retryable=True) from None
        except (
            TimeoutError,
            httpx.TimeoutException,
            httpx.NetworkError,
            httpx.ProtocolError,
            httpx.DecodingError,
        ):
            raise ProviderFailure("provider_outcome_unknown", outcome_unknown=True) from None
        try:
            decoded = json.loads(body)
            if decoded.get("promptFeedback", {}).get("blockReason"):
                raise ProviderFailure("provider_content_blocked")
            candidates = decoded.get("candidates", [])
            if not candidates:
                raise ProviderFailure("provider_empty_response")
            candidate = candidates[0]
            if candidate.get("finishReason") not in {"STOP", "MAX_TOKENS"}:
                raise ProviderFailure("provider_content_blocked")
            text = "".join(
                part.get("text", "")
                for part in candidate.get("content", {}).get("parts", [])
                if not part.get("thought", False)
            )
            if not text.strip():
                raise ProviderFailure("provider_empty_response")
            usage = decoded.get("usageMetadata", {})

            def count(name):
                value = usage.get(name)
                return value if type(value) is int and 0 <= value <= 100_000_000 else None

            return TextResponse(
                text,
                TokenUsage(
                    count("promptTokenCount"),
                    count("candidatesTokenCount"),
                    count("thoughtsTokenCount"),
                    count("totalTokenCount"),
                ),
                "live",
            )
        except (ValueError, TypeError, AttributeError, KeyError, IndexError):
            raise ProviderFailure("provider_invalid_response", outcome_unknown=True) from None
