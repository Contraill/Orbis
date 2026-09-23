"""Installation authority, localized metadata and provider-independent library data."""
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, Float, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.types import UTCDateTime
from db.models.profile import utc_now


class Installation(Base):
    __tablename__ = "installation"
    __table_args__ = (CheckConstraint("id = 1", name="installation_singleton"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    locale: Mapped[str] = mapped_column(String(5), default="en-US")
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("profiles.id", ondelete="RESTRICT"))
    password_hash: Mapped[str | None] = mapped_column(String(255))
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(UTCDateTime())


class AdminSession(Base):
    __tablename__ = "admin_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())


class LocalizedMetadata(Base):
    __tablename__ = "localized_metadata"
    # movie:ID, tv:ID, tv:ID:season:N; never includes a locale in canonical identity.
    content_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    locale: Mapped[str] = mapped_column(String(5), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON)
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class ViewingProgress(Base):
    __tablename__ = "viewing_progress"
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True)
    content_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    media_type: Mapped[str] = mapped_column(String(16))
    tmdb_id: Mapped[int] = mapped_column(Integer)
    season_number: Mapped[int | None] = mapped_column(Integer)
    episode_number: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    last_watched_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    sampled_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    last_position: Mapped[float] = mapped_column(Float, default=0)
    watched_seconds: Mapped[float] = mapped_column(Float, default=0)
    cycle_seconds: Mapped[float] = mapped_column(Float, default=0)
    completions: Mapped[int] = mapped_column(Integer, default=0)
    cycle_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    rewatches: Mapped[int] = mapped_column(Integer, default=0)
    cycle_rewatch_counted: Mapped[bool] = mapped_column(Boolean, default=False)


class ViewingDay(Base):
    __tablename__ = "viewing_days"
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True)
    content_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    day: Mapped[str] = mapped_column(String(10), primary_key=True)
    watched_seconds: Mapped[float] = mapped_column(Float, default=0)
    visits: Mapped[int] = mapped_column(Integer, default=0)
    completions: Mapped[int] = mapped_column(Integer, default=0)


class LibraryIntent(Base):
    __tablename__ = "library_intents"
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True)
    media_type: Mapped[str] = mapped_column(String(16), primary_key=True)
    tmdb_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    in_my_list: Mapped[bool] = mapped_column(Boolean, default=False)
    listed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    not_interested: Mapped[bool] = mapped_column(Boolean, default=False)
    feedback_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    hidden_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    hidden_watched_seconds: Mapped[float] = mapped_column(Float, default=0)
