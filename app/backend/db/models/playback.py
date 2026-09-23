from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Index,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    event,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.types import UTCDateTime


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PlaybackState(Base):
    __tablename__ = "playback_states"

    __table_args__ = (
        UniqueConstraint(
            "profile_id",
            "content_key",
            name="uq_playback_state_content",
        ),
        Index(
            "uq_playback_movie_identity",
            "profile_id",
            "tmdb_id",
            unique=True,
            sqlite_where=text("media_type = 'movie'"),
        ),
        Index(
            "uq_playback_episode_identity",
            "profile_id",
            "tmdb_id",
            "season_number",
            "episode_number",
            unique=True,
            sqlite_where=text("media_type = 'tv'"),
        ),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True,
    )

    profile_id: Mapped[int] = mapped_column(
        ForeignKey(
            "profiles.id",
            ondelete="CASCADE",
        ),
        index=True,
        nullable=False,
    )

    content_key: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    media_type: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
    )

    tmdb_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    season_number: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    episode_number: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    position_seconds: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        nullable=False,
    )

    duration_seconds: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    completed: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    last_provider_id: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
    )

    preferred_audio_language: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )

    preferred_provider_id: Mapped[str | None] = mapped_column(String(80))
    preferred_source_provider_id: Mapped[str | None] = mapped_column(String(80))
    preferred_source_id: Mapped[str | None] = mapped_column(String(80))
    preferred_quality_height: Mapped[int | None] = mapped_column(Integer)

    preferred_audio_kind: Mapped[str | None] = mapped_column(
        String(24),
        nullable=True,
    )

    subtitles_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    preferred_subtitle_language: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )

    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


def playback_content_key(
    media_type: str,
    tmdb_id: int,
    season_number: int | None = None,
    episode_number: int | None = None,
) -> str:
    if tmdb_id <= 0:
        raise ValueError("tmdb_id must be positive")

    if media_type == "movie":
        if season_number is not None or episode_number is not None:
            raise ValueError("Movies cannot have season or episode numbers")
        return f"movie:{tmdb_id}"

    if media_type == "tv":
        if season_number is None or season_number < 0:
            raise ValueError("TV playback requires a valid season number")
        if episode_number is None or episode_number <= 0:
            raise ValueError("TV playback requires a valid episode number")
        return (
            f"tv:{tmdb_id}:"
            f"s{season_number}:e{episode_number}"
        )

    raise ValueError("media_type must be 'movie' or 'tv'")


@event.listens_for(PlaybackState, "before_insert")
@event.listens_for(PlaybackState, "before_update")
def set_playback_content_key(
    mapper,
    connection,
    target: PlaybackState,
) -> None:
    target.content_key = playback_content_key(
        target.media_type,
        target.tmdb_id,
        target.season_number,
        target.episode_number,
    )
