"""Reported capabilities, not a device database. Unknown source codecs remain unknown."""
from contextvars import ContextVar
from pydantic import BaseModel, ConfigDict, Field

request_client = ContextVar("playback_client_context", default=None)


class ClientCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hls: bool = True
    dash: bool = True
    video_codecs: list[str] | None = Field(default=None, max_length=32)
    audio_codecs: list[str] | None = Field(default=None, max_length=32)
    max_height: int | None = Field(default=None, ge=144, le=8640)
    text_tracks: bool = True
    subtitle_formats: list[str] | None = Field(default=None, max_length=16)
    hdr: bool | None = None


class ClientCompatibilityError(ValueError):
    pass


def current_capabilities(fallback=None):
    ctx = request_client.get()
    if ctx is not None:
        return ClientCapabilities.model_validate(ctx["capabilities"]) if ctx["capabilities"] is not None else None
    return ClientCapabilities.model_validate(fallback) if fallback is not None else None


def codec_family(value):
    value = value.strip().lower().split(".")[0]
    return {"avc1": "h264", "avc3": "h264", "hvc1": "hevc", "hev1": "hevc", "h265": "hevc",
        "av01": "av1", "vp09": "vp9", "mp4a": "aac", "ac-3": "ac3", "ec-3": "eac3"}.get(value, value)


def compatible_codecs(values, supported):
    return supported is None or not values or all(codec_family(v) in {codec_family(s) for s in supported} for v in values)


def variant_compatible(height, video, audio, hdr, caps):
    if caps is None:
        return True
    return (not height or caps.max_height is None or height <= caps.max_height) and compatible_codecs(video, caps.video_codecs) and compatible_codecs(audio, caps.audio_codecs) and not (hdr and caps.hdr is False)


def source_compatible(source, caps):
    if caps is None:
        return True
    from providers.source_policy import quality_score
    if source.protocol == "hls" and not caps.hls or source.protocol == "dash" and not caps.dash:
        return False
    # A master playlist's nominal label is not a limit on its lower variants.
    height = quality_score(source.quality) if source.protocol == "http" else None
    return variant_compatible(height, [source.video_codec] if source.video_codec else [], [source.audio_codec] if source.audio_codec else [], source.hdr, caps)


def hls_attributes(line):
    import re
    attrs = dict((m[1], m[2].strip('"')) for m in re.finditer(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)', line))
    resolution = attrs.get("RESOLUTION", "").split("x")
    height = int(resolution[-1]) if len(resolution) == 2 and resolution[-1].isdigit() else None
    codecs = attrs.get("CODECS", "").split(",") if attrs.get("CODECS") else []
    audio = [c for c in codecs if codec_family(c) in {"aac", "ac3", "eac3", "opus", "vorbis", "flac", "mp3"}]
    return height, [c for c in codecs if c not in audio], audio, attrs.get("VIDEO-RANGE", "SDR") not in {"", "SDR"}


def filter_hls(text, caps):
    """Remove incompatible master variants before registering their resource URLs."""
    if caps is None or "#EXT-X-STREAM-INF:" not in text:
        return text
    output, pending, variants, kept = [], None, 0, 0
    for line in text.splitlines():
        value = line.strip()
        if value.startswith("#EXT-X-STREAM-INF:"):
            pending = line
            variants += 1
        elif pending is not None and value and not value.startswith("#"):
            if variant_compatible(*hls_attributes(pending), caps):
                output.extend([pending, line])
                kept += 1
            pending = None
        elif pending is None:
            # Optional trick-play variants can otherwise bypass codec/height eligibility.
            if value.startswith(("#EXT-X-I-FRAME-STREAM-INF:", "#EXT-X-IMAGE-STREAM-INF:")) and not variant_compatible(*hls_attributes(value), caps):
                continue
            output.append(line)
    if variants and not kept:
        raise ClientCompatibilityError("no_compatible_variant")
    return "\n".join(output) + "\n"
