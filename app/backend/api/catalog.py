from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.orm import Session
from db.session import get_db
from metadata.localization import preferred_locale, store_response

from metadata.schemas import CatalogDetails, CatalogPage, SeasonDetails
from metadata.tmdb import TMDBClient, TMDBError


router = APIRouter(prefix="/api/catalog", tags=["catalog"])
tmdb = TMDBClient("en-US")


def client(locale):
    return tmdb if locale == "en-US" else TMDBClient(locale)


def raise_tmdb_error(exc: TMDBError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail=exc.detail,
    ) from exc


@router.get("/search", response_model=CatalogPage)
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
    try:
        return store_response(db, locale, await client(locale).movie_details(tmdb_id))
    except TMDBError as exc:
        raise_tmdb_error(exc)


@router.get("/tv/{tmdb_id}", response_model=CatalogDetails)
async def tv_details(
    tmdb_id: int = Path(gt=0),
    locale: str = Depends(preferred_locale), db: Session = Depends(get_db),
):
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
    try:
        return store_response(db, locale, await client(locale).season_details(
            tmdb_id,
            season_number,
        ))
    except TMDBError as exc:
        raise_tmdb_error(exc)
