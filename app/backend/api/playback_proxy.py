import asyncio
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from core.auth import require_owner
from fastapi.responses import StreamingResponse

from playback.hls import read_manifest, rewrite_manifest
from playback.media_types import MISLABELED_MEDIA_TYPES, SNIFF_BYTES, media_type, probe_media_type, sniff_prefix
from playback.source_sessions import SourceSessionExpired, SourceSessionNotFound, source_sessions
from playback.upstream import UpstreamRejected, new_http_client, open_upstream


router = APIRouter(tags=["playback"])
logger = logging.getLogger(__name__)
UPSTREAM_RESPONSE_HEADERS = {
    "accept-ranges", "content-encoding", "content-length", "content-range",
    "content-type", "etag", "last-modified",
}
_new_http_client = new_http_client


async def _body(upstream, client, iterator=None, prefix=b""):
    try:
        if prefix:
            yield prefix
        async for chunk in iterator if iterator is not None else upstream.aiter_raw():
            yield chunk
    finally:
        await upstream.aclose()
        await client.aclose()


@router.get("/api/admin/playback/delivery", dependencies=[Depends(require_owner)])
def delivery_diagnostics():
    return source_sessions.diagnostics()


@router.head("/api/playback/sources/{session_id}", include_in_schema=False)
@router.head("/api/playback/sources/{session_id}/{resource_id}", include_in_schema=False)
@router.get("/api/playback/sources/{session_id}")
@router.get("/api/playback/sources/{session_id}/{resource_id}")
async def proxy_playback_source(session_id: str, request: Request, resource_id: str = "root"):
    try:
        session = source_sessions.get(session_id, for_proxy=True)
    except SourceSessionNotFound:
        raise HTTPException(404, "Playback source session not found")
    except SourceSessionExpired:
        raise HTTPException(410, "Playback source has expired")
    if request.query_params:
        raise HTTPException(400, "Playback resource parameters are not supported")
    resource = session.resources.get(resource_id)
    if resource is None:
        raise HTTPException(404, "Playback resource not found")
    if session.source.protocol not in {"http", "hls"}:
        raise HTTPException(409, "Playback delivery is not supported")
    # Existing direct-HTTP capabilities remain usable; public HTTP now uses direct AUTO.
    if resource.kind not in session.plan.relay and session.source.protocol != "http":
        raise HTTPException(409, "Playback resource is not available here")

    manifest = session.source.protocol == "hls" and resource.kind in {"root", "manifest"}
    range_headers = {
        name: request.headers[name] for name in ("range", "if-range")
        if name in request.headers and not manifest
    }
    client = _new_http_client()
    upstream = None
    try:
        upstream, final_url = await open_upstream(
            client, session.source, resource.url,
            method="GET" if manifest else request.method,
            range_headers=range_headers,
        )
        if upstream.status_code not in ({200} if manifest else {200, 206, 416}):
            logger.info("delivery_upstream_status session=%s kind=%s status=%d", session_id[:8], resource.kind, upstream.status_code)
            raise UpstreamRejected("Upstream status rejected")
        if manifest:
            async with asyncio.timeout(15):
                body = rewrite_manifest(session, resource, final_url, await read_manifest(upstream))
            await upstream.aclose()
            await client.aclose()
            return Response(
                content=body if request.method == "GET" else b"",
                media_type="application/vnd.apple.mpegurl",
                headers={"Cache-Control": "no-store", "Content-Length": str(len(body.encode()))},
            )
        headers = {name: value for name, value in upstream.headers.items() if name.lower() in UPSTREAM_RESPONSE_HEADERS}
        headers.update({"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})
        content_type = headers.get("content-type", "").split(";", 1)[0].lower()
        if content_type in {"application/xhtml+xml", "image/svg+xml", "application/javascript", "text/javascript"}:
            raise UpstreamRejected("Unexpected active content")
        html_segment = content_type == "text/html"
        if html_segment and (resource.kind not in {"segment", "init"} or upstream.status_code not in {200, 206}):
            raise UpstreamRejected("Unexpected active content")
        if resource.kind == "key":
            headers["content-type"] = "application/octet-stream"
        iterator, prefix = None, b""
        if (resource.kind in {"segment", "init"}
            and content_type in MISLABELED_MEDIA_TYPES
            and upstream.status_code in {200, 206}):
            known = session.context.setdefault("media_types", {})
            # Never trust a cached MIME for an active-content response: a CDN
            # can replace a previously valid segment with an HTML error page.
            detected = None if html_segment else known.get(resource.resource_id)
            if detected is None:
                starts_at_zero = upstream.status_code == 200 or upstream.headers.get("content-range", "").startswith("bytes 0-")
                if request.method == "GET" and starts_at_zero:
                    iterator = upstream.aiter_raw(chunk_size=16 * 1024)
                    async with asyncio.timeout(5):
                        prefix = await sniff_prefix(iterator)
                    detected = media_type(prefix)
                    if detected is None and upstream.status_code == 206 and len(prefix) < SNIFF_BYTES:
                        # A caller's short Range must not become a container-sniffing failure.
                        detected = await probe_media_type(
                            client, session.source, resource,
                            required="video/mp2t" if html_segment else None,
                        )
                    if detected is None:
                        raise UpstreamRejected("Unrecognized media container")
                else:
                    detected = await probe_media_type(
                        client, session.source, resource,
                        required="video/mp2t" if html_segment else None,
                    )
                if html_segment and detected != "video/mp2t":
                    raise UpstreamRejected("Unexpected active content")
                if not html_segment:
                    known[resource.resource_id] = detected
            headers["content-type"] = detected
        if request.method == "HEAD":
            await upstream.aclose()
            await client.aclose()
            return Response(status_code=upstream.status_code, headers=headers)
        return StreamingResponse(_body(upstream, client, iterator, prefix), status_code=upstream.status_code, headers=headers)
    except BaseException as exc:
        if upstream is not None:
            await upstream.aclose()
        await client.aclose()
        if isinstance(exc, (httpx.HTTPError, OSError, UpstreamRejected, TimeoutError)):
            logger.info("delivery_failed session=%s kind=%s reason=%s", session_id[:8], resource.kind, type(exc).__name__)
            raise HTTPException(502, "Playback resource could not be loaded") from exc
        raise
