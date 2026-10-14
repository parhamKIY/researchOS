import asyncio
import json

import httpx
import pytest
from pydantic import SecretStr

from researchos.providers.contracts import ProviderFailure, TextRequest
from researchos.providers.gemini import GeminiProvider
from researchos.providers.mock import MockProvider

REQUEST = TextRequest(
    model_name="explicit-gemini-test-model", prompt="Disposable connection fixture"
)
KEY = SecretStr("explicit-fixture-key-not-a-live-credential")


def test_real_adapter_contract_with_explicit_http_mock():
    def server(request):
        assert request.url.host == "generativelanguage.googleapis.com"
        assert "key=" not in str(request.url)
        assert request.headers["x-goog-api-key"] == KEY.get_secret_value()
        assert json.loads(request.content)["contents"][0]["parts"][0]["text"] == REQUEST.prompt
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {
                            "parts": [{"text": "private thought", "thought": True}, {"text": "OK"}]
                        },
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 7,
                    "candidatesTokenCount": 2,
                    "thoughtsTokenCount": 4,
                    "totalTokenCount": 13,
                },
            },
        )

    result = asyncio.run(GeminiProvider(httpx.MockTransport(server)).generate_text(REQUEST, KEY))
    assert result.text == "OK" and result.execution_mode == "live"
    assert result.usage.total_tokens == 13 and result.usage.thought_tokens == 4


@pytest.mark.parametrize(
    "status,code,retry,unknown",
    [
        (401, "provider_authentication_failed", False, False),
        (403, "provider_access_denied", False, False),
        (404, "model_unavailable", False, False),
        (429, "provider_rate_limited", True, False),
        (503, "provider_unavailable", False, True),
        (302, "provider_unavailable", False, False),
    ],
)
def test_errors_are_normalized_without_redirect_or_secret(status, code, retry, unknown):
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            status,
            json={"error": {"message": KEY.get_secret_value()}},
            headers={"Location": "https://untrusted.example/"},
        )
    )
    with pytest.raises(ProviderFailure) as error:
        asyncio.run(GeminiProvider(transport).generate_text(REQUEST, KEY))
    assert (
        str(error.value) == code
        and error.value.retryable == retry
        and error.value.outcome_unknown == unknown
    )


def test_read_timeout_is_not_retryable_because_outcome_is_unknown():
    def timeout(request):
        raise httpx.ReadTimeout("secret fixture response", request=request)

    with pytest.raises(ProviderFailure) as error:
        asyncio.run(GeminiProvider(httpx.MockTransport(timeout)).generate_text(REQUEST, KEY))
    assert error.value.outcome_unknown and not error.value.retryable
    assert "secret fixture" not in str(error.value)


def test_missing_usage_remains_unknown_and_mock_is_labeled():
    server = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            json={"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "OK"}]}}]},
        )
    )
    result = asyncio.run(GeminiProvider(server).generate_text(REQUEST, KEY))
    assert result.usage.total_tokens is None
    assert asyncio.run(MockProvider().generate_text(REQUEST, None)).execution_mode == "mock"
