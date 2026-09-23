"""Public, origin-allowlisted, DNS-pinned streaming fetches for delivery."""
import asyncio
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import httpx


class UpstreamRejected(ValueError):
    pass


def origin(url: str) -> str:
    try:
        parsed = urlsplit(url)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise UpstreamRejected("Invalid upstream URL") from exc
    if (
        parsed.scheme not in {"http", "https"} or not parsed.hostname
        or parsed.username is not None or parsed.password is not None
        or port not in {80, 443} or "\\" in url
        or any(ord(char) < 32 for char in url)
    ):
        raise UpstreamRejected("Invalid upstream URL")
    host = parsed.hostname.lower()
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if host == "localhost" or host.endswith((".localhost", ".local")):
            raise UpstreamRejected("Private upstream target")
    else:
        if not address.is_global:
            raise UpstreamRejected("Private upstream target")
    return f"{parsed.scheme}://{host}:{port}"


async def public_address(url: str) -> str:
    origin(url)
    parsed = urlsplit(url)
    async with asyncio.timeout(5):
        records = await asyncio.get_running_loop().getaddrinfo(
            parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    addresses = [item[4][0] for item in records]
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise UpstreamRejected("Non-public upstream DNS result")
    return addresses[0]


def new_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        follow_redirects=False, trust_env=False,
        timeout=httpx.Timeout(connect=10, read=20, write=10, pool=10),
    )


HOP_HEADERS = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade", "host",
    "range", "if-range", "accept-encoding", "content-length",
}


async def open_upstream(client, source, url, *, method="GET", range_headers=None):
    allowed = {origin(source.url), *(origin(item) for item in source.delivery.resource_origins)}
    for _ in range(4):
        current_origin = origin(url)
        if current_origin not in allowed:
            raise UpstreamRejected("Upstream origin is not allowed")
        address = await public_address(url)
        # Provider credentials stay on the source origin, never a CDN redirect.
        headers = {
            name: value for name, value in source.headers.items()
            if name.lower() not in HOP_HEADERS
        } if current_origin == origin(source.url) else {}
        # Per-origin non-secret grants are explicit and re-evaluated on every hop.
        # No credential inheritance from the original source or previous redirect.
        headers.update(source.delivery.resource_headers.get(current_origin, {}))
        headers.update(range_headers or {})
        headers["Accept-Encoding"] = "identity"
        target = httpx.URL(url)
        headers["Host"] = target.netloc.decode("ascii")
        client.cookies.clear()
        request = client.build_request(method, target.copy_with(host=address), headers=headers)
        # The connection is pinned to the checked address, TLS still verifies the hostname.
        request.extensions["sni_hostname"] = target.host
        response = await client.send(request, stream=True)
        if not response.is_redirect:
            return response, url
        location = response.headers.get("location")
        await response.aclose()
        if not location:
            raise UpstreamRejected("Missing redirect destination")
        next_url = urljoin(url, location)
        if urlsplit(url).scheme == "https" and urlsplit(next_url).scheme != "https":
            raise UpstreamRejected("HTTPS downgrade rejected")
        url = next_url
    raise UpstreamRejected("Too many upstream redirects")
