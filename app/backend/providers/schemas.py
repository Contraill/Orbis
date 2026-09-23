from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class DeliveryHints(BaseModel):
    # Normalized adapter knowledge, never application routes or platform names.
    egress: Literal["unknown", "independent", "resolution"] = "unknown"
    resource_origins: list[str] = Field(default_factory=list, max_length=64)
    # Only non-secret headers, explicitly scoped by a trusted adapter. Never inherited.
    resource_headers: dict[str, dict[str, str]] = Field(default_factory=dict, max_length=64)

    @model_validator(mode="after")
    def validate_resource_policy(self):
        def canonical(value):
            parsed = urlsplit(value)
            if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or "*" in value or "\\" in value or any(ord(c) <= 32 for c in value)
                or parsed.username is not None or parsed.password is not None
                or parsed.path not in {"", "/"} or parsed.query or parsed.fragment
                or parsed.port not in {None, 80, 443}):
                raise ValueError("Expected an exact HTTP(S) origin")
            return f"{parsed.scheme}://{parsed.hostname}:{parsed.port or (443 if parsed.scheme == 'https' else 80)}"

        origins = list(dict.fromkeys(canonical(item) for item in self.resource_origins))
        headers = {}
        for target, values in self.resource_headers.items():
            target = canonical(target)
            if target not in origins:
                raise ValueError("Resource headers require an explicitly trusted origin")
            scoped = {}
            for name, value in values.items():
                if name.lower() not in {"user-agent", "referer"}:
                    raise ValueError("Only User-Agent and Referer may cross origins")
                if not value or len(value) > 2048 or any(ord(c) < 32 or ord(c) == 127 for c in value):
                    raise ValueError("Invalid resource header")
                scoped[name.lower()] = value
            headers[target] = scoped
        self.resource_origins = origins
        self.resource_headers = headers
        return self


class PlaybackSource(BaseModel):
    provider_id: str
    # Stable adapter-local host/player key, never an embed/video/session ID.
    source_id: str | None = Field(default=None, max_length=80, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    source_label: str | None = Field(default=None, max_length=100)
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
    delivery: DeliveryHints = Field(default_factory=DeliveryHints)


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
