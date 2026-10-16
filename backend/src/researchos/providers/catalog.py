"""Credential-scoped discovery; catalog visibility does not prove generation access."""

import asyncio
import json
import re

import httpx
from pydantic import SecretStr

from researchos.providers.contracts import ProviderFailure
from researchos.providers.safe_http import PublicHTTPTransport, normalize_base_url

MAX_MODELS = 5000
MAX_PAGES = 20
ERROR_MESSAGES = {
    "provider_authentication_failed": "The provider rejected the API key.",
    "provider_access_denied": (
        "The provider denied access. Check API permissions, account restrictions and region."
    ),
    "provider_rate_limited": "The provider rate limit or quota was reached. Try again later.",
    "model_catalog_unsupported": (
        "This endpoint does not support model listing. Check the API base URL."
    ),
    "model_catalog_too_large": (
        "The model catalog exceeded the safety limit; no partial list was returned."
    ),
    "provider_invalid_response": "The provider returned an invalid model catalog.",
    "provider_response_too_large": "The provider model catalog response exceeded the size limit.",
    "provider_address_rejected": "The endpoint must resolve only to public network addresses.",
    "provider_dns_failed": "The provider hostname could not be resolved.",
    "provider_connection_failed": "A secure connection to the provider could not be established.",
    "provider_request_rejected": (
        "The provider rejected model listing. Check the API base URL and key."
    ),
    "provider_unavailable": "Model listing is temporarily unavailable.",
}


async def read_page(client, url, headers, params):
    async with client.stream("GET", url, headers=headers, params=params) as response:
        if response.status_code != 200:
            codes = {
                400: "provider_request_rejected",
                401: "provider_authentication_failed",
                403: "provider_access_denied",
                404: "model_catalog_unsupported",
                405: "model_catalog_unsupported",
                429: "provider_rate_limited",
            }
            raise ProviderFailure(codes.get(response.status_code, "provider_unavailable"))
        body = bytearray()
        async for chunk in response.aiter_bytes():
            if len(body) + len(chunk) > 2 * 1024 * 1024:
                raise ProviderFailure("provider_response_too_large")
            body.extend(chunk)
        try:
            decoded = json.loads(body)
            if not isinstance(decoded, dict):
                raise ValueError
            return decoded
        except (ValueError, TypeError):
            raise ProviderFailure("provider_invalid_response") from None


async def discover_models(adapter, base_url, key: SecretStr | None, *, transport=None):
    if adapter == "mock":
        return {
            "items": [{"id": "fixture-model", "display_name": "Mock · local fixture"}],
            "execution_mode": "mock",
        }
    if adapter not in {"gemini", "openai_compatible"}:
        raise ProviderFailure("provider_unsupported")
    if key is None:
        raise ProviderFailure("credential_unavailable")
    base_url = normalize_base_url(base_url)
    if adapter == "gemini" and base_url != "https://generativelanguage.googleapis.com/v1beta":
        raise ProviderFailure("provider_address_rejected")
    secret = key.get_secret_value()
    headers = (
        {"x-goog-api-key": secret} if adapter == "gemini" else {"Authorization": f"Bearer {secret}"}
    )
    items, seen_tokens = {}, set()
    params = {"pageSize": 1000} if adapter == "gemini" else {}
    try:
        async with (
            asyncio.timeout(20),
            httpx.AsyncClient(
                transport=transport or PublicHTTPTransport(httpx.URL(base_url).host),
                timeout=httpx.Timeout(10, connect=5),
                follow_redirects=False,
                trust_env=False,
            ) as client,
        ):
            for _ in range(MAX_PAGES):
                page = await read_page(client, f"{base_url}/models", headers, params)
                rows = page.get("models" if adapter == "gemini" else "data")
                if not isinstance(rows, list):
                    raise ProviderFailure("provider_invalid_response")
                for row in rows:
                    if not isinstance(row, dict):
                        raise ProviderFailure("provider_invalid_response")
                    if adapter == "gemini":
                        methods = row.get("supportedGenerationMethods", [])
                        if not isinstance(methods, list) or not all(
                            isinstance(item, str) for item in methods
                        ):
                            raise ProviderFailure("provider_invalid_response")
                        if "generateContent" not in methods:
                            continue
                        name = row.get("name", "")
                        identifier = name.removeprefix("models/") if isinstance(name, str) else ""
                        pattern = r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}"
                    else:
                        identifier = row.get("id", "")
                        pattern = r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}"
                    if not isinstance(identifier, str) or not re.fullmatch(pattern, identifier):
                        continue
                    label = row.get("displayName") if adapter == "gemini" else identifier
                    if (
                        not isinstance(label, str)
                        or len(label) > 200
                        or any(ord(c) < 32 for c in label)
                    ):
                        label = identifier
                    # An untrusted endpoint may reflect a credential in its catalog.
                    if secret in identifier or secret in label:
                        continue
                    items[identifier] = {"id": identifier, "display_name": label}
                    if len(items) > MAX_MODELS:
                        raise ProviderFailure("model_catalog_too_large")
                if adapter == "gemini":
                    token = page.get("nextPageToken")
                    if not token:
                        break
                    if not isinstance(token, str) or len(token) > 2048 or token in seen_tokens:
                        raise ProviderFailure("provider_invalid_response")
                    seen_tokens.add(token)
                    params["pageToken"] = token
                else:
                    # OpenAI uses one page; support compatible providers with cursor pagination.
                    more = page.get("has_more", False)
                    if not isinstance(more, bool):
                        raise ProviderFailure("provider_invalid_response")
                    if not more:
                        break
                    token = page.get("last_id")
                    if (
                        not isinstance(token, str)
                        or not token
                        or len(token) > 200
                        or token in seen_tokens
                    ):
                        raise ProviderFailure("provider_invalid_response")
                    seen_tokens.add(token)
                    params["after"] = token
            else:
                raise ProviderFailure("model_catalog_too_large")
    except (httpx.ConnectError, httpx.ConnectTimeout):
        raise ProviderFailure("provider_connection_failed") from None
    except (TimeoutError, httpx.HTTPError):
        raise ProviderFailure("provider_unavailable") from None
    return {"items": sorted(items.values(), key=lambda item: item["id"]), "execution_mode": "live"}
