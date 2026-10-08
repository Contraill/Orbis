"""Bounded container detection for mislabeled, server-attested HLS resources."""
import asyncio

from playback.upstream import UpstreamRejected, open_upstream


# Require seven complete, aligned transport packets before accepting a TS
# container. This also bounds the separate zero-based probe used for HEAD and
# nonzero Range requests.
TS_PACKET_BYTES = 188
TS_PACKETS_REQUIRED = 7
SNIFF_BYTES = TS_PACKET_BYTES * TS_PACKETS_REQUIRED
MISLABELED_MEDIA_TYPES = {
    "application/x-mpegurl", "application/vnd.apple.mpegurl",
    "audio/mpegurl", "audio/x-mpegurl", "image/png", "image/jpeg", "text/html",
}


def media_type(prefix: bytes) -> str | None:
    # A sync byte alone is insufficient: require seven complete packets with
    # valid, non-reserved adaptation-field control in every TS header.
    if len(prefix) >= SNIFF_BYTES and all(
        prefix[offset] == 0x47 and (prefix[offset + 3] & 0x30) != 0
        for offset in range(0, SNIFF_BYTES, TS_PACKET_BYTES)
    ):
        return "video/mp2t"
    if len(prefix) >= 16 and prefix[4:8] in {b"ftyp", b"styp", b"moof"}:
        size = int.from_bytes(prefix[:4], "big")
        if size >= 8:
            return "video/mp4"
    return None


async def sniff_prefix(iterator) -> bytes:
    """Read only the bounded prefix needed for container identification."""
    prefix = bytearray()
    async for chunk in iterator:
        prefix.extend(chunk)
        if len(prefix) >= SNIFF_BYTES:
            break
    return bytes(prefix)


async def probe_media_type(client, source, resource, *, required: str | None = None) -> str:
    response = None
    try:
        async with asyncio.timeout(5):
            response, _ = await open_upstream(
                client, source, resource.url,
                range_headers={"Range": f"bytes=0-{SNIFF_BYTES - 1}"},
            )
            if response.status_code not in {200, 206}:
                raise UpstreamRejected("Container probe was rejected")
            prefix = await sniff_prefix(response.aiter_raw(chunk_size=SNIFF_BYTES))
            detected = media_type(prefix)
            if detected is None or (required is not None and detected != required):
                raise UpstreamRejected("Unrecognized media container")
            return detected
    finally:
        if response is not None:
            await response.aclose()
