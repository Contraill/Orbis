"""Bounded HLS parsing: only resources attested by upstream manifests are registered."""
import re
from urllib.parse import urljoin

from playback.source_sessions import source_sessions
from playback.upstream import UpstreamRejected


MAX_MANIFEST_BYTES = 1024 * 1024
URI_ATTRIBUTE = re.compile(r'(?P<prefix>(?:[:,])(?:URI)=)"(?P<uri>[^"\r\n]+)"')
URI_KINDS = {
    "#EXT-X-MEDIA": "manifest",
    "#EXT-X-I-FRAME-STREAM-INF": "manifest",
    "#EXT-X-IMAGE-STREAM-INF": "manifest",
    "#EXT-X-RENDITION-REPORT": "manifest",
    "#EXT-X-KEY": "key",
    "#EXT-X-SESSION-KEY": "key",
    "#EXT-X-MAP": "init",
    "#EXT-X-PART": "segment",
    "#EXT-X-PRELOAD-HINT": "segment",
}


def resource_path(session, resource):
    root = f"/api/playback/sources/{session.session_id}"
    return root if resource.kind == "root" else f"{root}/{resource.resource_id}"


def resource_url(session, resource):
    return resource_path(session, resource) if resource.kind in session.plan.relay else resource.url


async def read_manifest(response):
    body = bytearray()
    async for chunk in response.aiter_bytes():
        body.extend(chunk)
        if len(body) > MAX_MANIFEST_BYTES:
            raise UpstreamRejected("Manifest size limit exceeded")
    try:
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise UpstreamRejected("Invalid manifest encoding") from exc
    if not text.startswith("#EXTM3U"):
        raise UpstreamRejected("Upstream is not an HLS manifest")
    return text


def rewrite_manifest(session, parent, base_url, text):
    output = []
    next_is_manifest = False

    def rewrite(uri, kind):
        if "{$" in uri:
            raise UpstreamRejected("HLS variables are not supported")
        resource = source_sessions.register(session, parent, urljoin(base_url, uri), kind)
        return resource_url(session, resource)

    for line in text.splitlines():
        if len(line) > 16384:
            raise UpstreamRejected("Manifest line limit exceeded")
        value = line.strip()
        tag = value.split(":", 1)[0]
        if tag in {"#EXT-X-CONTENT-STEERING", "#EXT-X-DEFINE"}:
            raise UpstreamRejected("Unsupported HLS indirection")
        if value and not value.startswith("#"):
            output.append(rewrite(value, "manifest" if next_is_manifest else "segment"))
            next_is_manifest = False
            continue
        if tag == "#EXT-X-STREAM-INF":
            next_is_manifest = True
        if re.search(r"[:,]URI=", value):
            kind = URI_KINDS.get(tag)
            if not kind or not URI_ATTRIBUTE.search(value):
                raise UpstreamRejected("Unsupported manifest URI attribute")
            if tag == "#EXT-X-PRELOAD-HINT" and "TYPE=MAP" in value:
                kind = "init"
            line = URI_ATTRIBUTE.sub(
                lambda match: f'{match["prefix"]}"{rewrite(match["uri"], kind)}"', value,
            )
        output.append(line)
    return "\n".join(output) + "\n"
