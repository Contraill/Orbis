"""Canonical TMDB cache, relationships and source-independent ratings."""
from datetime import datetime
from sqlalchemy import ForeignKey, Index, Integer, JSON, String, Float
from sqlalchemy.orm import Mapped, mapped_column
from db.base import Base
from db.types import UTCDateTime
from db.models.profile import utc_now


class CatalogEntity(Base):
    __tablename__ = "catalog_entities"
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), index=True)
    tmdb_id: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(512))
    # Normalized locale-independent features; never raw TMDB payloads.
    features: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class CatalogLink(Base):
    __tablename__ = "catalog_links"
    media_key: Mapped[str] = mapped_column(ForeignKey("catalog_entities.key", ondelete="CASCADE"), primary_key=True)
    entity_key: Mapped[str] = mapped_column(ForeignKey("catalog_entities.key", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str] = mapped_column(String(128), primary_key=True)
    character: Mapped[str] = mapped_column(String(512), primary_key=True, default="")
    __table_args__ = (Index("ix_catalog_links_entity_role", "entity_key", "role", "media_key"),)


class CatalogRating(Base):
    __tablename__ = "catalog_ratings"
    source: Mapped[str] = mapped_column(String(64), primary_key=True)
    external_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    average: Mapped[float] = mapped_column(Float)
    votes: Mapped[int] = mapped_column(Integer)
    scale: Mapped[float] = mapped_column(Float, default=10)
    provenance: Mapped[str] = mapped_column(String(512))
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class SearchCache(Base):
    __tablename__ = "catalog_search_cache"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)


class CatalogSeason(Base):
    __tablename__ = "catalog_seasons"
    series_key: Mapped[str] = mapped_column(ForeignKey("catalog_entities.key", ondelete="CASCADE"), primary_key=True)
    season_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    tmdb_id: Mapped[int] = mapped_column(Integer)
    air_date: Mapped[str | None] = mapped_column(String(10))
    episode_count: Mapped[int | None] = mapped_column(Integer)


class CatalogEpisode(Base):
    __tablename__ = "catalog_episodes"
    series_key: Mapped[str] = mapped_column(ForeignKey("catalog_entities.key", ondelete="CASCADE"), primary_key=True)
    season_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    episode_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    tmdb_id: Mapped[int | None] = mapped_column(Integer)
    air_date: Mapped[str | None] = mapped_column(String(10))
    runtime_minutes: Mapped[int | None] = mapped_column(Integer)
