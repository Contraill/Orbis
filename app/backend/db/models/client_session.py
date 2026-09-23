from datetime import datetime
from sqlalchemy import ForeignKey, String, JSON, Float
from sqlalchemy.orm import Mapped, mapped_column
from db.base import Base
from db.types import UTCDateTime
from db.models.profile import utc_now


class ClientSession(Base):
    __tablename__ = "client_sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), index=True)
    audience: Mapped[str] = mapped_column(String(64))
    display_name: Mapped[str] = mapped_column(String(100))
    client_type: Mapped[str] = mapped_column(String(32))
    capabilities: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    last_seen: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, index=True)
    state: Mapped[str] = mapped_column(String(16), default="idle")
    current_playback: Mapped[dict | None] = mapped_column(JSON)
    source_session_id: Mapped[str | None] = mapped_column(String(128))
    position_seconds: Mapped[float] = mapped_column(Float, default=0)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    stopped_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class ContentMarkers(Base):
    __tablename__ = "content_markers"
    content_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    markers: Mapped[dict] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String(100))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
