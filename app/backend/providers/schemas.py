from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


PlaybackProtocol = Literal["hls", "dash", "http"]
ProviderStatus = Literal[
    "unknown",
    "healthy",
    "degraded",
    "circuit_open",
    "disabled",
]

AudioKind = Literal[
    "original",
    "dub",
    "commentary",
    "unknown",
]

SubtitleKind = Literal[
    "external",
    "manifest",
    "burned_in",
]


class AudioTrack(BaseModel):
    language: str | None = None
    label: str | None = None
    kind: AudioKind = "unknown"
    track_id: str | None = None


class SubtitleTrack(BaseModel):
    language: str | None = None
    label: str | None = None
    kind: SubtitleKind
    url: str | None = None
    format: str | None = None
    track_id: str | None = None
    forced: bool = False


class PlaybackSource(BaseModel):
    provider_id: str
    url: str
    protocol: PlaybackProtocol

    quality: str | None = None

    audio_tracks: list[AudioTrack] = Field(
        default_factory=list
    )

    subtitle_tracks: list[SubtitleTrack] = Field(
        default_factory=list
    )

    headers: dict[str, str] = Field(
        default_factory=dict
    )

    expires_at: datetime | None = None


class ProviderCapabilities(BaseModel):
    movie: bool = True
    episode: bool = True

    protocols: list[PlaybackProtocol] = Field(
        default_factory=list
    )

    selectable_audio: bool = False
    selectable_subtitles: bool = False
    burned_in_subtitles: bool = False


class ProviderSearchResult(BaseModel):
    provider_id: str
    external_id: str
    title: str
    year: int | None = None


class ProviderHealthResult(BaseModel):
    healthy: bool
    message: str | None = None


class ProviderAttempt(BaseModel):
    provider_id: str
    status: Literal["success", "failed", "skipped"]
    latency_ms: float | None = None
    error: str | None = None


class PlaybackResolution(BaseModel):
    selected_provider_id: str
    sources: list[PlaybackSource]
    attempts: list[ProviderAttempt]


class ProviderAdminView(BaseModel):
    provider_id: str
    name: str
    enabled: bool
    priority: int
    status: ProviderStatus
    capabilities: ProviderCapabilities
    failure_count: int

    circuit_open_until: datetime | None = None
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    last_health_check_at: datetime | None = None
    last_latency_ms: float | None = None
    last_error: str | None = None


class ProviderHealthCheckReport(BaseModel):
    provider: ProviderAdminView
    healthy: bool
    message: str | None = None
    latency_ms: float


class ProviderEventView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    provider_id: str
    level: str
    event: str
    message: str | None
    created_at: datetime
