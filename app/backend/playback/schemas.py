from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from providers.schemas import (
    AudioKind,
    AudioTrack,
    PlaybackProtocol,
    ProviderAttempt,
    SubtitleTrack,
)
from providers.source_policy import SourceExpiryStatus


MediaType = Literal["movie", "tv"]


def normalize_language(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = value.strip().replace("_", "-").lower()
    return normalized or None


class PlaybackPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preferred_provider_id: str | None = Field(default=None, max_length=80, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    preferred_source_provider_id: str | None = Field(default=None, max_length=80, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    preferred_source_id: str | None = Field(default=None, max_length=80, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    preferred_quality_height: int | None = Field(default=None, ge=144, le=8640)

    @model_validator(mode="after")
    def source_scope(self):
        if bool(self.preferred_source_id) != bool(self.preferred_source_provider_id):
            raise ValueError("Source preference requires its provider scope")
        return self


class PlaybackStateUpdate(PlaybackPreferences):
    model_config = ConfigDict(extra="forbid")

    position_seconds: float = Field(
        default=0,
        ge=0,
        allow_inf_nan=False,
    )
    duration_seconds: float | None = Field(
        default=None,
        gt=0,
        allow_inf_nan=False,
    )
    completed: bool = False
    last_provider_id: str | None = Field(
        default=None,
        max_length=80,
    )
    preferred_audio_language: str | None = Field(
        default=None,
        max_length=32,
    )
    preferred_audio_kind: AudioKind | None = None
    subtitles_enabled: bool = False
    preferred_subtitle_language: str | None = Field(
        default=None,
        max_length=32,
    )

    @field_validator(
        "preferred_audio_language",
        "preferred_subtitle_language",
    )
    @classmethod
    def validate_language(
        cls,
        value: str | None,
    ) -> str | None:
        return normalize_language(value)

    @field_validator("last_provider_id")
    @classmethod
    def validate_provider_id(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class PlaybackStateView(PlaybackPreferences):
    model_config = ConfigDict(from_attributes=True)

    profile_id: int
    media_type: MediaType
    tmdb_id: int
    season_number: int | None
    episode_number: int | None
    position_seconds: float
    duration_seconds: float | None
    completed: bool
    last_provider_id: str | None
    preferred_audio_language: str | None
    preferred_audio_kind: AudioKind | None
    subtitles_enabled: bool
    preferred_subtitle_language: str | None
    resume_position_seconds: float
    updated_at: datetime


class AudioSelection(BaseModel):
    track: AudioTrack | None = None
    matched_by: Literal[
        "language_and_kind",
        "track_id",
        "language",
        "kind",
        "base_language_and_kind",
        "base_language",
        "provider_default",
        "none",
    ]


class SubtitleSelection(BaseModel):
    enabled: bool
    can_disable: bool
    selected_track: SubtitleTrack | None = None
    burned_in_track: SubtitleTrack | None = None


class PlaybackResolutionSummary(BaseModel):
    selected_provider_id: str
    attempts: list[ProviderAttempt]


class PlaybackClientSource(BaseModel):
    provider_id: str
    source_id: str | None = None
    source_label: str | None = None
    url: str
    protocol: PlaybackProtocol
    quality: str | None = None
    audio_tracks: list[AudioTrack]
    subtitle_tracks: list[SubtitleTrack]
    expires_at: datetime | None = None


class PlaybackSession(BaseModel):
    client_session_id: str | None = None
    preparation_only: bool = False
    state: PlaybackStateView
    resolution: PlaybackResolutionSummary
    selected_source: PlaybackClientSource
    source_session_id: str
    source_expires_at: datetime | None
    source_expiry_status: SourceExpiryStatus
    refresh_at: datetime | None
    selected_audio: AudioSelection
    selected_subtitles: SubtitleSelection
    choices: "PlaybackChoices" = Field(default_factory=lambda: PlaybackChoices())


class QualityChoice(BaseModel):
    height: int
    label: str


class SourceChoice(BaseModel):
    source_id: str
    label: str


class ProviderChoice(BaseModel):
    provider_id: str
    label: str


class PlaybackChoices(BaseModel):
    providers: list[ProviderChoice] = Field(default_factory=list)
    sources: list[SourceChoice] = Field(default_factory=list)
    qualities: list[QualityChoice] = Field(default_factory=list)
    selected_quality_height: int | None = None
    max_compatible_height: int | None = None
    quality_outcome: Literal["auto", "exact", "unavailable_fallback", "incompatible_fallback", "unverified"] = "auto"


class PlaybackTransitionRequest(PlaybackStateUpdate):
    preferred_audio_track_id: str | None = Field(
        default=None,
        max_length=160,
    )
    preferred_subtitle_track_id: str | None = Field(
        default=None,
        max_length=160,
    )


class PlaybackFailoverRequest(PlaybackTransitionRequest):
    failed_provider_id: str = Field(
        min_length=1,
        max_length=80,
    )


class PlaybackRefreshRequest(PlaybackTransitionRequest):
    source_session_id: str = Field(
        min_length=32,
        max_length=128,
    )


class PlaybackFailure(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: Literal["network", "media", "other"] = "other"
    resource_type: Literal["manifest", "segment", "init", "key", "subtitle", "unknown"] = "unknown"
    http_status: int | None = Field(default=None, ge=100, le=599)
    code: int | None = Field(default=None, ge=0, le=99999)


class PlaybackRecoverRequest(PlaybackRefreshRequest):
    failure: PlaybackFailure


class EpisodeMarkers(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intro_start: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    intro_end: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    recap_start: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    recap_end: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    credits_start: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    credits_end: float | None = Field(default=None, ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def ordered_ranges(self):
        for name in ("intro", "recap", "credits"):
            start, end = getattr(self, name + "_start"), getattr(self, name + "_end")
            if start is not None and end is not None and end <= start:
                raise ValueError(f"{name}_end must be after {name}_start")
        return self


class EpisodeReference(BaseModel):
    media_type: Literal["tv"] = "tv"
    tmdb_id: int
    season_number: int
    episode_number: int
    content_key: str
    episode_tmdb_id: int | None = None
    title: str | None = None
    air_date: str | None = None
    aired: bool = False


class EpisodeLifecycle(BaseModel):
    current: EpisodeReference
    previous: EpisodeReference | None = None
    next: EpisodeReference | None = None
    next_status: Literal["available", "unreleased", "series_finished", "metadata_incomplete"]
    season_transition: bool
    is_season_final: bool
    is_final_season: bool
    is_final_episode: bool
    autoplay_next: bool
    autoplay_allowed: bool
    resume_position_seconds: float
    current_completed: bool
    markers: EpisodeMarkers
    marker_source: str | None = None
    warning: str | None = None
