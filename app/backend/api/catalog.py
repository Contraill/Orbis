from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.orm import Session
from db.session import get_db
from metadata.localization import preferred_locale, store_response

from metadata.schemas import CatalogDetails, CatalogPage, SeasonDetails, CursorPage, UnifiedSearchPage, GenreSearchPage
from metadata.tmdb import TMDBClient, TMDBError
from metadata.catalog import cached, ratings
from metadata import search as unified


router = APIRouter(prefix="/api/catalog", tags=["catalog"])
tmdb = TMDBClient("en-US")


def client(locale):
    return tmdb if locale == "en-US" else TMDBClient(locale)


def raise_tmdb_error(exc: TMDBError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail=exc.detail,
    ) from exc


@router.get("/search", response_model=CatalogPage, deprecated=True)
async def search_catalog(
    query: str = Query(min_length=1, max_length=200),
    page: int = Query(default=1, ge=1, le=500),
    locale: str = Depends(preferred_locale), db: Session = Depends(get_db),
):
    query = query.strip()

    if not query:
        raise HTTPException(
            status_code=422,
            detail="Search query cannot be empty",
        )

    try:
        return store_response(db, locale, await client(locale).search(query, page))
    except TMDBError as exc:
        raise_tmdb_error(exc)


@router.get("/trending", response_model=CatalogPage)
async def trending_catalog(
    window: Literal["day", "week"] = "day",
    locale: str = Depends(preferred_locale), db: Session = Depends(get_db),
):
    try:
        return store_response(db, locale, await client(locale).trending(window))
    except TMDBError as exc:
        raise_tmdb_error(exc)


@router.get("/movie/{tmdb_id}", response_model=CatalogDetails)
async def movie_details(
    tmdb_id: int = Path(gt=0),
    locale: str = Depends(preferred_locale), db: Session = Depends(get_db),
):
    hit = cached(db, f"movie:{tmdb_id}", locale, details=True)
    if hit:
        return hit
    try:
        return store_response(db, locale, await client(locale).movie_details(tmdb_id))
    except TMDBError as exc:
        raise_tmdb_error(exc)


@router.get("/tv/{tmdb_id}", response_model=CatalogDetails)
async def tv_details(
    tmdb_id: int = Path(gt=0),
    locale: str = Depends(preferred_locale), db: Session = Depends(get_db),
):
    hit = cached(db, f"tv:{tmdb_id}", locale, details=True)
    if hit:
        return hit
    try:
        return store_response(db, locale, await client(locale).tv_details(tmdb_id))
    except TMDBError as exc:
        raise_tmdb_error(exc)


@router.get(
    "/tv/{tmdb_id}/season/{season_number}",
    response_model=SeasonDetails,
)
async def season_details(
    tmdb_id: int = Path(gt=0),
    season_number: int = Path(ge=0),
    locale: str = Depends(preferred_locale), db: Session = Depends(get_db),
):
    hit = cached(db, f"tv:{tmdb_id}:season:{season_number}", locale)
    if hit:
        return hit
    try:
        return store_response(db, locale, await client(locale).season_details(
            tmdb_id,
            season_number,
        ))
    except TMDBError as exc:
        raise_tmdb_error(exc)


@router.get("/unified-search", response_model=UnifiedSearchPage)
async def unified_search(
    query: str = Query(min_length=1, max_length=200),
    kind: Literal["all", "movie", "tv", "person", "company"] = "all",
    limit: int = Query(default=20, ge=1, le=50),
    cursor: str | None = Query(default=None, max_length=64),
    online: bool = False,
    locale: str = Depends(preferred_locale), db: Session = Depends(get_db),
):
    return await unified.search(db, client(locale), query, locale, kind, limit, cursor, online)


@router.get("/items", response_model=CursorPage)
def catalog_items(
    kind: Literal["all", "movie", "tv"] = "all",
    limit: int = Query(default=20, ge=1, le=50),
    cursor: str | None = Query(default=None, max_length=64),
    my_list: bool = False, profile_id: int | None = Query(default=None, gt=0),
    locale: str = Depends(preferred_locale), db: Session = Depends(get_db),
):
    if my_list and profile_id is None:
        raise HTTPException(422, "My List requires a profile")
    return unified.surface(db, locale, kind, limit, cursor, profile_id, my_list)


@router.get("/genres", response_model=GenreSearchPage)
def search_genres(
    query: str = Query(min_length=2, max_length=80),
    kind: Literal["all", "movie", "tv"] = "all",
    locale: str = Depends(preferred_locale), db: Session = Depends(get_db),
):
    from sqlalchemy import select
    from db.models.catalog import CatalogEntity, CatalogFeature
    from metadata.genres import genre_ids, search
    results = []
    for genre in search(query, kind, locale):
        terms = [f"genre:{value}" for value in genre_ids(genre["genre_id"], kind)]
        statement = select(CatalogFeature.media_key).join(CatalogEntity, CatalogEntity.key == CatalogFeature.media_key)
        statement = statement.where(CatalogFeature.term.in_(terms))
        if kind != "all":
            statement = statement.where(CatalogEntity.kind == kind)
        if db.scalar(statement.limit(1)):
            results.append(genre)
    return {"results": results}


@router.get("/genres/{genre_id}/items")
def genre_items(
    genre_id: int = Path(gt=0), kind: Literal["all", "movie", "tv"] = "all",
    limit: int = Query(default=24, ge=1, le=50),
    cursor: str | None = Query(default=None, max_length=64),
    locale: str = Depends(preferred_locale), db: Session = Depends(get_db),
):
    from metadata.genres import label
    title = label(genre_id, kind, locale)
    if title is None:
        raise HTTPException(404, "Unknown genre")
    return {"genre_id": genre_id, "title": title, "scope": kind,
            **unified.surface(db, locale, kind, limit, cursor, genre_id=genre_id)}


@router.get("/person/{tmdb_id}/credits", response_model=CursorPage)
async def credits(
    tmdb_id: int = Path(gt=0), limit: int = Query(default=20, ge=1, le=50),
    cursor: str | None = Query(default=None, max_length=64), enrich: bool = False,
    locale: str = Depends(preferred_locale), db: Session = Depends(get_db),
):
    if enrich and not cursor:
        try:
            await unified.person_credits(db, client(locale), tmdb_id, locale)
        except TMDBError as exc:
            raise_tmdb_error(exc)
    return unified.surface(db, locale, limit=limit, cursor=cursor, entity_key=f"person:{tmdb_id}")


@router.get("/company/{tmdb_id}/credits", response_model=CursorPage)
def company_credits(
    tmdb_id: int = Path(gt=0), limit: int = Query(default=20, ge=1, le=50),
    cursor: str | None = Query(default=None, max_length=64),
    locale: str = Depends(preferred_locale), db: Session = Depends(get_db),
):
    return unified.surface(db, locale, limit=limit, cursor=cursor, entity_key=f"company:{tmdb_id}")


@router.get("/{kind}/{tmdb_id}/ratings")
def catalog_ratings(kind: Literal["movie", "tv"], tmdb_id: int = Path(gt=0), db: Session = Depends(get_db)):
    return {"ratings": ratings(db, f"{kind}:{tmdb_id}")}
