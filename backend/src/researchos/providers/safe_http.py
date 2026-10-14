"""Public HTTPS endpoints with DNS validation at the actual TCP connection."""

import asyncio
import ipaddress
import re
import socket
import ssl
from urllib.parse import urlsplit

import httpcore
import httpx

from researchos.providers.contracts import ProviderFailure


def normalize_base_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        if (
            value != value.strip()
            or parsed.scheme != "https"
            or parsed.port not in {None, 443}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or len(value) > 500
            or not re.fullmatch(r"[a-zA-Z0-9.-]+", host)
            or len(host) > 253
            or "." not in host
            or host.endswith(".")
            or any(
                not re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", label)
                for label in host.split(".")
            )
            or host.lower().endswith((".localhost", ".local", ".internal", ".invalid"))
            or not re.fullmatch(r"/[a-zA-Z0-9/_-]*|", parsed.path)
            or "//" in parsed.path
        ):
            raise ValueError
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError
        return f"https://{host.lower()}{parsed.path.rstrip('/')}"
    except ValueError:
        raise ValueError("Use a public HTTPS API base URL on port 443") from None


async def resolve_public(host: str) -> list[str]:
    try:
        rows = await asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        addresses = list(dict.fromkeys(row[4][0] for row in rows))
        if not addresses or len(addresses) > 32:
            raise ProviderFailure("provider_address_rejected")
        for address in addresses:
            ip = ipaddress.ip_address(address)
            if (
                not ip.is_global
                or ip.is_multicast
                or ip.is_reserved
                or getattr(ip, "ipv4_mapped", None)
            ):
                raise ProviderFailure("provider_address_rejected")
        return addresses
    except (OSError, ValueError):
        raise ProviderFailure("provider_dns_failed") from None


class PublicNetworkBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, allowed_host: str, backend=None, resolver=resolve_public):
        self.host = allowed_host
        self.backend = backend
        self.resolver = resolver

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        if host != self.host or port != 443 or local_address is not None:
            raise ProviderFailure("provider_address_rejected")
        addresses = await self.resolver(host)
        # Connect to the validated literal IP; httpcore retains the original host for TLS/SNI.
        backend = self.backend or httpcore.AnyIOBackend()
        return await backend.connect_tcp(
            addresses[0], port, timeout=timeout, socket_options=socket_options
        )

    async def connect_unix_socket(self, *args, **kwargs):
        raise ProviderFailure("provider_address_rejected")

    async def sleep(self, seconds):
        await asyncio.sleep(seconds)


class CoreResponseStream(httpx.AsyncByteStream):
    def __init__(self, stream):
        self.stream = stream

    async def __aiter__(self):
        async for chunk in self.stream:
            yield chunk

    async def aclose(self):
        await self.stream.aclose()


class PublicHTTPTransport(httpx.AsyncBaseTransport):
    def __init__(self, host: str, *, backend=None):
        self.host = host
        self.pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl.create_default_context(),
            network_backend=backend or PublicNetworkBackend(host),
            max_connections=1,
            max_keepalive_connections=0,
            retries=0,
        )

    async def handle_async_request(self, request):
        if (
            request.url.scheme != "https"
            or request.url.host != self.host
            or request.url.port not in {None, 443}
        ):
            raise ProviderFailure("provider_address_rejected")
        core_request = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
        try:
            response = await self.pool.handle_async_request(core_request)
        except (httpcore.ConnectError, httpcore.ConnectTimeout):
            raise ProviderFailure("provider_connection_failed") from None
        except (httpcore.TimeoutException, httpcore.NetworkError, httpcore.ProtocolError):
            raise ProviderFailure("provider_outcome_unknown", outcome_unknown=True) from None
        return httpx.Response(
            response.status,
            headers=response.headers,
            stream=CoreResponseStream(response.stream),
            extensions=response.extensions,
        )

    async def aclose(self):
        await self.pool.aclose()
