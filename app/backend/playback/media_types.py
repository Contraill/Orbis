"""Bounded container detection for mislabeled, server-attested HLS resources."""
import asyncio

from playback.upstream import UpstreamRejected, open_upstream


SNIFF_BYTES = 3 * 188
MISLABELED_MEDIA_TYPES = {
    "application/x-mpegurl", "application/vnd.apple.mpegurl",
    "audio/mpegurl", "audio/x-mpegurl", "image/png", "image/jpeg",
}


def media_type(prefix: bytes) -> str | None:
    # Three aligned TS packet sync bytes, not merely a leading letter G.
    if len(prefix) >= SNIFF_BYTES and all(prefix[offset] == 0x47 for offset in (0, 188, 376)):
        return "video/mp2t"
    if len(prefix) >= 16 and prefix[4:8] in {b"ftyp", b"styp", b"moof"}:
        size = int.from_bytes(prefix[:4], "big")
        if size >= 8:
            return "video/mp4"
    return None


async def probe_media_type(client, source, resource) -> str:
    response = None
    try:
        async with asyncio.timeout(5):
            response, _ = await open_upstream(
                client, source, resource.url,
                range_headers={"Range": f"bytes=0-{SNIFF_BYTES - 1}"},
            )
            if response.status_code not in {200, 206}:
                raise UpstreamRejected("Container probe was rejected")
            prefix = await anext(response.aiter_raw(chunk_size=SNIFF_BYTES), b"")
            detected = media_type(prefix)
            if detected is None:
                raise UpstreamRejected("Unrecognized media container")
            return detected
    finally:
        if response is not None:
            await response.aclose()
