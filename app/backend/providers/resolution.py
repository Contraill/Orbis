"""Resolution transport seam, independent of downstream media delivery."""
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Literal, Protocol

import httpx


ResolutionMode = Literal["auto", "server_http", "browser_http", "real_browser", "client_egress"]


class ResolutionTransport(Protocol):
    async def get(self, url: str, *, headers: dict[str, str] | None = None) -> httpx.Response: ...
    async def aclose(self) -> None: ...


class ResolutionCapabilityUnavailable(RuntimeError):
    pass


class ResolutionBroker:
    def __init__(self):
        self._active: ContextVar[dict | None] = ContextVar("resolution_transports", default=None)
        self.real_browser_factory: Callable[[], ResolutionTransport] | None = None

    @asynccontextmanager
    async def session(self) -> AsyncIterator[None]:
        transports = {}
        token = self._active.set(transports)
        try:
            yield
        finally:
            self._active.reset(token)
            for transport in transports.values():
                await transport.aclose()

    def _new(self, mode):
        if mode == "client_egress":
            raise ResolutionCapabilityUnavailable("Client-egress resolution is not installed")
        if mode == "real_browser":
            if self.real_browser_factory is None:
                raise ResolutionCapabilityUnavailable("Real-browser resolution is not installed")
            return self.real_browser_factory()
        headers = {}
        if mode == "browser_http":
            # Header/cookie semantics; this does not emulate browser TLS or JavaScript.
            headers = {"User-Agent": "Mozilla/5.0", "Accept": "text/html,application/xhtml+xml"}
        return httpx.AsyncClient(headers=headers, follow_redirects=False, timeout=7)

    async def get(self, url, *, headers=None, mode: ResolutionMode = "auto"):
        active = self._active.get()
        if active is None:
            async with self.session():
                return await self.get(url, headers=headers, mode=mode)
        if mode == "auto":
            response = await self.get(url, headers=headers, mode="server_http")
            if response.status_code == 403:
                return await self.get(url, headers=headers, mode="browser_http")
            return response
        if mode not in active:
            active[mode] = self._new(mode)
        return await active[mode].get(url, headers=headers)

    async def probe_media(self, source, url, *, client_factory=None) -> bytes:
        """Bounded standard HTTP probe using the same exact-origin/DNS policy as delivery.

        Adapters see normalized metadata only; no relay routes or client details.
        """
        import asyncio
        from playback.upstream import new_http_client, open_upstream, UpstreamRejected

        async with asyncio.timeout(5), (client_factory or new_http_client)() as client:
            response, _ = await open_upstream(client, source, url, range_headers={"Range": "bytes=0-187"})
            try:
                if response.status_code not in {200, 206}:
                    raise UpstreamRejected("Media probe was rejected")
                async for chunk in response.aiter_bytes():
                    if chunk:
                        return chunk[:188]
                raise UpstreamRejected("Media probe returned an empty body")
            finally:
                await response.aclose()


resolution_broker = ResolutionBroker()
