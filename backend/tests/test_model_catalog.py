import asyncio
import json

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from researchos.api.admin_schemas import GEMINI_BASE, SystemProviderWrite
from researchos.providers.catalog import discover_models
from researchos.providers.contracts import ProviderFailure

KEY = "explicit-catalog-fixture-key-not-live"


def discover(server, adapter="gemini"):
    return asyncio.run(
        discover_models(
            adapter,
            GEMINI_BASE if adapter == "gemini" else "https://api.example.com/v1",
            SecretStr(KEY),
            transport=httpx.MockTransport(server),
        )
    )


def test_gemini_catalog_uses_header_paginates_filters_and_normalizes():
    calls = []

    def server(request):
        calls.append(request)
        assert request.method == "GET" and request.url.path == "/v1beta/models"
        assert request.headers["x-goog-api-key"] == KEY and KEY not in str(request.url)
        assert request.url.params["pageSize"] == "1000"
        if len(calls) == 1:
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "name": "models/text-b",
                            "displayName": "Text B",
                            "supportedGenerationMethods": ["generateContent"],
                        },
                        {
                            "name": "models/embedding",
                            "supportedGenerationMethods": ["embedContent"],
                        },
                        {
                            "name": f"models/{KEY}",
                            "supportedGenerationMethods": ["generateContent"],
                        },
                    ],
                    "nextPageToken": "second",
                },
            )
        assert request.url.params["pageToken"] == "second"
        return httpx.Response(
            200,
            json={
                "models": [
                    {"name": "models/text-a", "supportedGenerationMethods": ["generateContent"]},
                    {
                        "name": "models/text-b",
                        "displayName": "Text B",
                        "supportedGenerationMethods": ["generateContent"],
                    },
                ]
            },
        )

    result = discover(server)
    assert result == {
        "items": [
            {"id": "text-a", "display_name": "text-a"},
            {"id": "text-b", "display_name": "Text B"},
        ],
        "execution_mode": "live",
    }
    assert len(calls) == 2 and KEY not in json.dumps(result)


def test_compatible_catalog_uses_safe_base_and_optional_cursor():
    calls = []

    def server(request):
        calls.append(request)
        assert request.url.host == "api.example.com" and request.url.path == "/v1/models"
        assert request.headers["Authorization"] == f"Bearer {KEY}"
        if len(calls) == 1:
            return httpx.Response(
                200,
                json={
                    "data": [{"id": "vendor/model-b"}],
                    "has_more": True,
                    "last_id": "vendor/model-b",
                },
            )
        assert request.url.params["after"] == "vendor/model-b"
        return httpx.Response(
            200, json={"data": [{"id": "model-a"}, {"id": KEY}, {"id": "invalid model"}]}
        )

    result = discover(server, "openai_compatible")
    assert [item["id"] for item in result["items"]] == ["model-a", "vendor/model-b"]
    assert KEY not in json.dumps(result)


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "provider_authentication_failed"),
        (403, "provider_access_denied"),
        (404, "model_catalog_unsupported"),
        (405, "model_catalog_unsupported"),
        (429, "provider_rate_limited"),
        (302, "provider_unavailable"),
        (503, "provider_unavailable"),
    ],
)
def test_catalog_failure_does_not_follow_redirect_or_echo_error(status, code):
    calls = []

    def server(request):
        calls.append(request)
        return httpx.Response(
            status, json={"error": KEY}, headers={"Location": "https://private.example/"}
        )

    with pytest.raises(ProviderFailure, match=f"^{code}$"):
        discover(server)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "payload", [[], {}, {"models": {}}, {"models": [42]}, {"models": [], "nextPageToken": 42}]
)
def test_malformed_catalog_is_rejected(payload):
    with pytest.raises(ProviderFailure, match="provider_invalid_response"):
        discover(lambda _: httpx.Response(200, json=payload))


def test_repeated_page_token_and_oversized_response_are_rejected():
    with pytest.raises(ProviderFailure, match="provider_invalid_response"):
        discover(lambda _: httpx.Response(200, json={"models": [], "nextPageToken": "loop"}))
    with pytest.raises(ProviderFailure, match="provider_response_too_large"):
        discover(lambda _: httpx.Response(200, content=b" " * (2 * 1024 * 1024 + 1)))


def test_catalog_timeout_is_sanitized_and_not_retried():
    calls = []

    def server(request):
        calls.append(request)
        raise httpx.ReadTimeout(KEY, request=request)

    with pytest.raises(ProviderFailure, match="^provider_unavailable$"):
        discover(server)
    assert len(calls) == 1


def test_empty_catalog_and_mock_do_not_invent_live_models():
    assert discover(lambda _: httpx.Response(200, json={"models": []}))["items"] == []
    result = asyncio.run(discover_models("mock", None, None))
    assert result["execution_mode"] == "mock" and result["items"][0]["id"] == "fixture-model"


@pytest.mark.parametrize(
    "body",
    [
        {"adapter": "gemini", "base_url": "https://other.example.com/v1"},
        {"adapter": "openai_compatible", "base_url": "http://127.0.0.1"},
        {"adapter": "openai_compatible", "base_url": "https://api.example.com/v1?key=secret"},
        {"adapter": "mock", "api_key": KEY},
        {"adapter": "gemini", "api_key": "invalid\nkey"},
    ],
)
def test_catalog_input_rejects_unsafe_endpoints_and_credentials(body):
    with pytest.raises(ValidationError):
        SystemProviderWrite.model_validate(body)
