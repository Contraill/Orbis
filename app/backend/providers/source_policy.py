import re
from datetime import datetime, timedelta, timezone
from typing import Literal
from urllib.parse import urlsplit

from providers.schemas import (
    AudioKind,
    AudioTrack,
    PlaybackSource,
    SubtitleTrack,
)


SOURCE_REFRESH_WINDOW = timedelta(minutes=2)
SUPPORTED_PROTOCOLS = {"hls", "dash", "http"}
SourceExpiryStatus = Literal["expired", "near_expiry", "healthy"]


class SourceSelectionError(ValueError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def source_expiry_status(
    source: PlaybackSource,
    *,
    now: datetime | None = None,
) -> SourceExpiryStatus:
    if source.expires_at is None:
        return "healthy"

    current = aware_utc(now or utc_now())
    expires_at = aware_utc(source.expires_at)
    if expires_at <= current:
        return "expired"
    if expires_at <= current + SOURCE_REFRESH_WINDOW:
        return "near_expiry"
    return "healthy"


def source_refresh_at(
    source: PlaybackSource,
    *,
    now: datetime | None = None,
) -> datetime | None:
    if source.expires_at is None:
        return None
    current = aware_utc(now or utc_now())
    return max(
        current,
        aware_utc(source.expires_at) - SOURCE_REFRESH_WINDOW,
    )


def source_validation_error(
    source: PlaybackSource,
    *,
    require_healthy: bool = False,
    now: datetime | None = None,
) -> str | None:
    parsed = urlsplit(source.url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return "Source URL must be an HTTP(S) URL without credentials"

    if source.protocol not in SUPPORTED_PROTOCOLS:
        return "Source protocol is not supported"

    if source.headers and source.protocol != "http":
        return (
            "Adaptive sources with custom headers require manifest "
            "proxying"
        )

    expiry = source_expiry_status(source, now=now)
    if expiry == "expired":
        return "Source has expired"
    if require_healthy and expiry == "near_expiry":
        return "Source expires too soon for a refreshed session"
    return None


def usable_sources(
    sources: list[PlaybackSource],
    *,
    require_healthy: bool = False,
    now: datetime | None = None,
) -> list[PlaybackSource]:
    return [
        source
        for source in sources
        if source_validation_error(
            source,
            require_healthy=require_healthy,
            now=now,
        )
        is None
    ]


def quality_score(value: str | None) -> int:
    if value is None:
        return 0

    normalized = value.strip().lower()
    match = re.search(r"(?<!\d)(\d{3,4})\s*p\b", normalized)
    if match:
        return int(match.group(1))

    if re.search(r"\b(8k|4320)\b", normalized):
        return 4320
    if re.search(r"\b(4k|uhd|2160)\b", normalized):
        return 2160
    if re.search(r"\b(full[ -]?hd|fhd|1080)\b", normalized):
        return 1080
    if re.search(r"\b(hd|720)\b", normalized):
        return 720
    if re.search(r"\b(sd|576|480)\b", normalized):
        return 480
    return 0


def _normalize_language(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().replace("_", "-").lower()
    return normalized or None


def _audio_preference_score(
    tracks: list[AudioTrack],
    language: str | None,
    kind: AudioKind | None,
    track_id: str | None,
) -> int:
    if track_id and any(track.track_id == track_id for track in tracks):
        return 4
    normalized = _normalize_language(language)
    if normalized and kind and any(
        _normalize_language(track.language) == normalized
        and track.kind == kind
        for track in tracks
    ):
        return 3
    if normalized and any(
        _normalize_language(track.language) == normalized
        for track in tracks
    ):
        return 2
    if kind and any(track.kind == kind for track in tracks):
        return 1
    return 0


def _subtitle_preference_score(
    tracks: list[SubtitleTrack],
    language: str | None,
    track_id: str | None,
) -> int:
    selectable = [
        track for track in tracks if track.kind != "burned_in"
    ]
    if track_id and any(
        track.track_id == track_id for track in selectable
    ):
        return 2
    normalized = _normalize_language(language)
    if normalized and any(
        _normalize_language(track.language) == normalized
        for track in selectable
    ):
        return 1
    return 0


def rank_sources(
    sources: list[PlaybackSource],
    *,
    preferred_audio_language: str | None = None,
    preferred_audio_kind: AudioKind | None = None,
    preferred_audio_track_id: str | None = None,
    subtitles_enabled: bool = False,
    preferred_subtitle_language: str | None = None,
    preferred_subtitle_track_id: str | None = None,
    require_healthy: bool = False,
    now: datetime | None = None,
) -> list[PlaybackSource]:
    current = aware_utc(now or utc_now())
    candidates = usable_sources(
        sources,
        require_healthy=require_healthy,
        now=current,
    )
    protocol_scores = {"hls": 3, "dash": 2, "http": 1}

    def key(source: PlaybackSource):
        expiry = source_expiry_status(source, now=current)
        expires_at = (
            aware_utc(source.expires_at).timestamp()
            if source.expires_at is not None
            else float("inf")
        )
        return (
            -(1 if expiry == "healthy" else 0),
            -_audio_preference_score(
                source.audio_tracks,
                preferred_audio_language,
                preferred_audio_kind,
                preferred_audio_track_id,
            ),
            -(
                _subtitle_preference_score(
                    source.subtitle_tracks,
                    preferred_subtitle_language,
                    preferred_subtitle_track_id,
                )
                if subtitles_enabled
                else 0
            ),
            -quality_score(source.quality),
            -protocol_scores[source.protocol],
            -expires_at,
            source.url,
        )

    return sorted(candidates, key=key)


def select_source(
    sources: list[PlaybackSource],
    **preferences,
) -> PlaybackSource:
    ranked = rank_sources(sources, **preferences)
    if not ranked:
        raise SourceSelectionError("No compatible playback source")
    return ranked[0]
