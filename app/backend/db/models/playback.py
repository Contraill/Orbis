from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


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
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )
