from typing import Literal
from pydantic import BaseModel, Field
from metadata.schemas import SearchResult

Surface = Literal["home", "movies", "series"]


class FeedItem(SearchResult):
    resume: dict | None = None


class Shelf(BaseModel):
    id: str
    title: str
    kind: str
    personalized: bool = False
    items: list[FeedItem]
    context_key: str | None = None


class FeedPage(BaseModel):
    snapshot_id: str
    surface: Surface
    personalized: bool
    shelves: list[Shelf]
    next_cursor: str | None = None
    warnings: list[str] = Field(default_factory=list)
