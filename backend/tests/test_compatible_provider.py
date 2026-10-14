import asyncio
import json
import socket

import httpcore
import httpx
import pytest
from pydantic import SecretStr

from researchos.providers.compatible import CompatibleProvider
from researchos.providers.contracts import ProviderFailure, TextRequest
from researchos.providers.safe_http import (
    PublicHTTPTransport,
    PublicNetworkBackend,
    normalize_base_url,
    resolve_public,
)


@pytest.mark.parametrize(
    "url",
    [
        "http://api.example.com/v1",
        "https://localhost/v1",
        "https://127.0.0.1/v1",
        "https://[::1]/v1",
        "https://api.local/v1",
        "https://a.internal",
        "https://a.example.com:8443",
        "https://user:key@api.example.com",
        "https://api.example.com/?key=secret",
        "https://api.example.com/#fragment",
        "https://api.example.com/%2e%2e/",
        "https://api.example.com/a/../b",
        "https://api.example.com\\@localhost",
        " https://api.example.com",
        "https://api.example.com//v1",
    ],
)
def test_reject_unsafe_urls(url):
    with pytest.raises(ValueError):
        normalize_base_url(url)


def test_url_normalization():
    assert (
        normalize_base_url("https://API.Example.com:443/api/v1/")
        == "https://api.example.com/api/v1"
    )


@pytest.mark.parametrize(
    "addresses",
    [
        ["127.0.0.1"],
        ["10.0.0.1"],
        ["169.254.169.254"],
        ["::1"],
        ["fc00::1"],
        ["::ffff:8.8.8.8"],
        ["8.8.8.8", "192.168.0.1"],
        ["224.0.0.1"],
        [],
    ],
)
def test_dns_rejects_all_non_public_and_mixed_answers(monkeypatch, addresses):
    async def run():
        async def lookup(*args, **kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in addresses]

        monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", lookup)
        with pytest.raises(ProviderFailure, match="provider_address_rejected"):
            await resolve_public("api.example.com")

    asyncio.run(run())


def test_transport_pins_ip_preserves_original_host_and_tls_sni():
    class Stream(httpcore.AsyncNetworkStream):
        def __init__(self):
            self.server_hostname = None
            self.written = b""
            self.sent = False

        async def read(self, max_bytes, timeout=None):
            if self.sent:
                return b""
            self.sent = True
            return b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nOK"

        async def write(self, buffer, timeout=None):
            self.written += buffer

        async def aclose(self):
            pass

        async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
            assert ssl_context.check_hostname
            self.server_hostname = server_hostname
            return self

        def get_extra_info(self, info):
            return None

    class Network(httpcore.AsyncNetworkBackend):
        def __init__(self):
            self.connected = None
            self.stream = Stream()

        async def connect_tcp(self, host, port, **kwargs):
            self.connected = (host, port)
            return self.stream

    async def run():
        calls = []

        async def resolver(host):
            calls.append(host)
            return ["8.8.8.8"]

        network = Network()
        backend = PublicNetworkBackend("api.example.com", network, resolver)
        async with httpx.AsyncClient(
            transport=PublicHTTPTransport("api.example.com", backend=backend)
        ) as client:
            response = await client.post(
                "https://api.example.com/v1/chat/completions", json={"fixture": True}
            )
            assert response.text == "OK"
        assert calls == ["api.example.com"]
        assert network.connected == ("8.8.8.8", 443)
        assert network.stream.server_hostname == "api.example.com"
        assert b"Host: api.example.com\r\n" in network.stream.written
        with pytest.raises(ProviderFailure):
            await backend.connect_tcp("localhost", 443)

    asyncio.run(run())


def fixture_response():
    return {
        "choices": [{"finish_reason": "stop", "message": {"content": "OK"}}],
        "usage": {"prompt_tokens": 7, "completion_tokens": 1, "total_tokens": 8},
    }


def test_compatible_protocol_model_headers_and_usage():
    def handler(request):
        assert str(request.url) == "https://api.example.com/api/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer explicit-fixture-key"
        payload = json.loads(request.content)
        assert payload["model"] == "vendor/fixture-model"
        assert payload["messages"] == [{"role": "user", "content": "Connectivity check"}]
        assert payload["max_completion_tokens"] == 256 and payload["stream"] is False
        return httpx.Response(200, json=fixture_response())

    result = asyncio.run(
        CompatibleProvider(
            "https://api.example.com/api/v1", transport=httpx.MockTransport(handler)
        ).generate_text(
            TextRequest(
                model_name="vendor/fixture-model",
                prompt="Connectivity check",
                parameters={"max_output_tokens": 256},
            ),
            SecretStr("explicit-fixture-key"),
        )
    )
    assert result.execution_mode == "live" and result.usage.total_tokens == 8


@pytest.mark.parametrize(
    "status,code",
    [
        (301, "provider_unavailable"),
        (401, "provider_authentication_failed"),
        (429, "provider_rate_limited"),
        (503, "provider_unavailable"),
    ],
)
def test_compatible_failure_never_redirects_retries_or_echoes_response(status, code):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            status, text="secret provider error", headers={"Location": "http://127.0.0.1"}
        )

    with pytest.raises(ProviderFailure) as failure:
        asyncio.run(
            CompatibleProvider(
                "https://api.example.com/v1", transport=httpx.MockTransport(handler)
            ).generate_text(
                TextRequest(model_name="fixture", prompt="test"), SecretStr("explicit-fixture-key")
            )
        )
    assert len(calls) == 1 and failure.value.code == code
    assert "secret" not in str(failure.value)


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"choices": []},
        {"choices": [{"finish_reason": "stop", "message": {"content": ""}}]},
        {"choices": [{"finish_reason": "tool_calls", "message": {"content": "OK"}}]},
    ],
)
def test_invalid_or_empty_success_response_fails(body):
    with pytest.raises(ProviderFailure):
        asyncio.run(
            CompatibleProvider(
                "https://api.example.com/v1",
                transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body)),
            ).generate_text(TextRequest(model_name="fixture", prompt="test"), SecretStr("fixture"))
        )
