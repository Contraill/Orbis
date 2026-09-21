from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

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


class PlaybackStateUpdate(BaseModel):
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


class PlaybackStateView(BaseModel):
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
    url: str
    protocol: PlaybackProtocol
    quality: str | None = None
    audio_tracks: list[AudioTrack]
    subtitle_tracks: list[SubtitleTrack]
    expires_at: datetime | None = None


class PlaybackSession(BaseModel):
    state: PlaybackStateView
    resolution: PlaybackResolutionSummary
    selected_source: PlaybackClientSource
    source_session_id: str
    source_expires_at: datetime | None
    source_expiry_status: SourceExpiryStatus
    refresh_at: datetime | None
    selected_audio: AudioSelection
    selected_subtitles: SubtitleSelection


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
