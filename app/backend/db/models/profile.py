from datetime import datetime, timezone

from sqlalchemy import String, Boolean, JSON, Index, text
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.types import UTCDateTime


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Profile(Base):
    __tablename__ = "profiles"
    __table_args__ = (Index("uq_profiles_owner", "is_owner", unique=True, sqlite_where=text("is_owner = 1")),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(
        String(80),
        unique=True,
        index=True,
        nullable=False,
    )
    avatar: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    avatar_seed: Mapped[str] = mapped_column(String(255), default="orbis", server_default="orbis")
    avatar_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    locale: Mapped[str] = mapped_column(String(5), default="en-US", server_default="en-US")
    is_owner: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    preferred_audio_language: Mapped[str | None] = mapped_column(String(32))
    preferred_subtitle_language: Mapped[str | None] = mapped_column(String(32))
    subtitles_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    autoplay_next_episode: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    trailer_muted: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    onboarding_seeds: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=utc_now,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )
