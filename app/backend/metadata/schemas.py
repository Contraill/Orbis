from typing import Literal

from pydantic import BaseModel, Field


MediaType = Literal["movie", "tv"]


class CatalogItem(BaseModel):
    tmdb_id: int
    media_type: MediaType
    title: str
    original_title: str | None = None
    overview: str = ""
    poster_url: str | None = None
    backdrop_url: str | None = None
    release_date: str | None = None
    vote_average: float | None = None


class CatalogPage(BaseModel):
    page: int
    total_pages: int
    results: list[CatalogItem]


class CatalogDetails(CatalogItem):
    genres: list[str] = Field(default_factory=list)
    runtime_minutes: int | None = None
    status: str | None = None
    number_of_seasons: int | None = None
    number_of_episodes: int | None = None


class EpisodeSummary(BaseModel):
    episode_number: int
    name: str
    overview: str = ""
    air_date: str | None = None
    still_url: str | None = None
    runtime_minutes: int | None = None
    vote_average: float | None = None


class SeasonDetails(BaseModel):
    series_tmdb_id: int
    season_tmdb_id: int
    season_number: int
    name: str
    overview: str = ""
    air_date: str | None = None
    poster_url: str | None = None
    episodes: list[EpisodeSummary] = Field(default_factory=list)
