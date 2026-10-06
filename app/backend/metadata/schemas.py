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
    genre_ids: list[int] = Field(default_factory=list)
    original_language: str | None = None
    countries: list[str] = Field(default_factory=list)
    popularity: float = 0


class CatalogPage(BaseModel):
    page: int
    total_pages: int
    results: list[CatalogItem]


class NamedReference(BaseModel):
    tmdb_id: int
    name: str


class Credit(NamedReference):
    role: str
    character: str = ""
    department: str | None = None
    order: int | None = None


class Video(BaseModel):
    site: str
    key: str
    name: str = ""
    language: str | None = None
    country: str | None = None
    type: str
    official: bool = False
    published_at: str | None = None


class SeasonSummary(BaseModel):
    tmdb_id: int
    season_number: int
    name: str
    overview: str = ""
    air_date: str | None = None
    episode_count: int = 0
    poster_url: str | None = None


class CatalogDetails(CatalogItem):
    collection_id: int | None = None
    genre_refs: list[NamedReference] = Field(default_factory=list)
    keywords: list[NamedReference] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    external_ids: dict[str, str] = Field(default_factory=dict)
    original_language: str | None = None
    countries: list[str] = Field(default_factory=list)
    production_companies: list[NamedReference] = Field(default_factory=list)
    credits: list[Credit] = Field(default_factory=list)
    videos: list[Video] = Field(default_factory=list)
    seasons: list[SeasonSummary] = Field(default_factory=list)
    related: list[dict[str, str | int]] = Field(default_factory=list)
    genres: list[str] = Field(default_factory=list)
    runtime_minutes: int | None = None
    status: str | None = None
    number_of_seasons: int | None = None
    number_of_episodes: int | None = None


class EpisodeSummary(BaseModel):
    tmdb_id: int | None = None
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


class SearchResult(BaseModel):
    key: str
    kind: Literal["movie", "tv", "person", "company"]
    tmdb_id: int
    title: str
    roles: list[str] = Field(default_factory=list)
    media_type: MediaType | None = None
    original_title: str | None = None
    overview: str = ""
    poster_url: str | None = None
    backdrop_url: str | None = None
    release_date: str | None = None
    vote_average: float | None = None
    display_locale: str | None = None
    score: float | None = None


class CursorPage(BaseModel):
    results: list[SearchResult]
    next_cursor: str | None = None


class UnifiedSearchPage(CursorPage):
    groups: dict[str, list[SearchResult]]
    warning: str | None = None
    candidate_limit: int = 600


class GenreSearchResult(BaseModel):
    genre_id: int
    title: str
    scope: Literal["all", "movie", "tv"]


class GenreSearchPage(BaseModel):
    results: list[GenreSearchResult]
