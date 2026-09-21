from collections.abc import AsyncIterator

import httpx
from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse

from playback.source_sessions import (
    SourceSessionExpired,
    SourceSessionNotFound,
    source_sessions,
)


router = APIRouter(
    prefix="/api/playback/sources",
    tags=["playback"],
)

CLIENT_REQUEST_HEADERS = {"range", "if-range"}
UPSTREAM_RESPONSE_HEADERS = {
    "accept-ranges",
    "cache-control",
    "content-disposition",
    "content-encoding",
    "content-length",
    "content-range",
    "content-type",
    "etag",
    "last-modified",
}
HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "host",
}


def _new_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        follow_redirects=False,
        timeout=httpx.Timeout(
            connect=10,
            read=None,
            write=10,
            pool=10,
        ),
    )


def _upstream_headers(
    provider_headers: dict[str, str],
    request: Request,
) -> dict[str, str]:
    headers = {
        name: value
        for name, value in provider_headers.items()
        if name.lower() not in HOP_BY_HOP_HEADERS
        and name.lower() not in CLIENT_REQUEST_HEADERS
    }
    for name in CLIENT_REQUEST_HEADERS:
        value = request.headers.get(name)
        if value is not None:
            headers[name] = value
    return headers


async def _body(
    upstream: httpx.Response,
    client: httpx.AsyncClient,
) -> AsyncIterator[bytes]:
    try:
        async for chunk in upstream.aiter_raw():
            yield chunk
    finally:
        await upstream.aclose()
        await client.aclose()


@router.api_route(
    "/{session_id}",
    methods=["GET", "HEAD"],
)
async def proxy_playback_source(
    session_id: str,
    request: Request,
):
    try:
        session = source_sessions.get(
            session_id,
            for_proxy=True,
        )
    except SourceSessionNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Playback source session not found",
        )
    except SourceSessionExpired:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Playback source has expired",
        )

    if session.source.protocol != "http":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This source does not use the direct media proxy",
        )

    client = _new_http_client()
    try:
        upstream_request = client.build_request(
            request.method,
            session.source.url,
            headers=_upstream_headers(
                session.source.headers,
                request,
            ),
        )
        upstream = await client.send(
            upstream_request,
            stream=True,
        )
    except httpx.HTTPError as exc:
        await client.aclose()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Playback source could not be reached",
        ) from exc

    response_headers = {
        name: value
        for name, value in upstream.headers.items()
        if name.lower() in UPSTREAM_RESPONSE_HEADERS
    }

    if 300 <= upstream.status_code < 400:
        await upstream.aclose()
        await client.aclose()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Playback source redirect is not supported",
        )

    if upstream.status_code not in {200, 206, 416}:
        await upstream.aclose()
        await client.aclose()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Playback source returned an invalid response",
        )

    if request.method == "HEAD":
        await upstream.aclose()
        await client.aclose()
        return Response(
            status_code=upstream.status_code,
            headers=response_headers,
        )

    return StreamingResponse(
        _body(upstream, client),
        status_code=upstream.status_code,
        headers=response_headers,
    )
