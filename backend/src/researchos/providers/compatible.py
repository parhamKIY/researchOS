import asyncio
import json

import httpcore
import httpx
from pydantic import SecretStr

from researchos.providers.contracts import ProviderFailure, TextRequest, TextResponse, TokenUsage
from researchos.providers.safe_http import PublicHTTPTransport, normalize_base_url


class CompatibleProvider:
    def __init__(self, base_url: str, *, transport: httpx.AsyncBaseTransport | None = None):
        self.base_url = normalize_base_url(base_url)
        self.transport = transport

    async def generate_text(self, request: TextRequest, key: SecretStr | None) -> TextResponse:
        if key is None:
            raise ProviderFailure("credential_unavailable")
        payload = {
            "model": request.model_name,
            "messages": [{"role": "user", "content": request.prompt}],
            "max_completion_tokens": request.parameters.max_output_tokens or 1024,
            "stream": False,
        }
        if request.parameters.temperature is not None:
            payload["temperature"] = request.parameters.temperature
        try:
            async with (
                asyncio.timeout(15),
                httpx.AsyncClient(
                    transport=self.transport or PublicHTTPTransport(httpx.URL(self.base_url).host),
                    timeout=httpx.Timeout(10, connect=5),
                    trust_env=False,
                    follow_redirects=False,
                ) as client,
            ):
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {key.get_secret_value()}"},
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
            raise ProviderFailure("provider_connection_failed") from None
        except (
            TimeoutError,
            httpx.HTTPError,
            httpcore.TimeoutException,
            httpcore.NetworkError,
            httpcore.ProtocolError,
        ):
            raise ProviderFailure("provider_outcome_unknown", outcome_unknown=True) from None
        try:
            decoded = json.loads(body)
            choice = decoded["choices"][0]
            text = choice["message"]["content"]
            if choice.get("finish_reason") not in {"stop", "length"} or choice["message"].get(
                "refusal"
            ):
                raise ProviderFailure("provider_content_blocked")
            if not isinstance(text, str) or not text.strip():
                raise ProviderFailure("provider_empty_response")
            usage = decoded.get("usage") or {}

            def count(name):
                value = usage.get(name)
                return value if type(value) is int and 0 <= value <= 100_000_000 else None

            return TextResponse(
                text,
                TokenUsage(
                    count("prompt_tokens"), count("completion_tokens"), None, count("total_tokens")
                ),
                "live",
            )
        except (ValueError, TypeError, AttributeError, KeyError, IndexError):
            raise ProviderFailure("provider_invalid_response", outcome_unknown=True) from None
