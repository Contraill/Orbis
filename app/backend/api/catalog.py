from typing import Literal

from fastapi import APIRouter, HTTPException, Path, Query

from metadata.schemas import CatalogDetails, CatalogPage, SeasonDetails
from metadata.tmdb import TMDBClient, TMDBError


router = APIRouter(prefix="/api/catalog", tags=["catalog"])
tmdb = TMDBClient()


def raise_tmdb_error(exc: TMDBError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail=exc.detail,
    ) from exc


@router.get("/search", response_model=CatalogPage)
async def search_catalog(
    query: str = Query(min_length=1, max_length=200),
    page: int = Query(default=1, ge=1, le=500),
):
    query = query.strip()

    if not query:
        raise HTTPException(
            status_code=422,
            detail="Search query cannot be empty",
        )

    try:
        return await tmdb.search(query, page)
    except TMDBError as exc:
        raise_tmdb_error(exc)


@router.get("/trending", response_model=CatalogPage)
async def trending_catalog(
    window: Literal["day", "week"] = "day",
):
    try:
        return await tmdb.trending(window)
    except TMDBError as exc:
        raise_tmdb_error(exc)


@router.get("/movie/{tmdb_id}", response_model=CatalogDetails)
async def movie_details(
    tmdb_id: int = Path(gt=0),
):
    try:
        return await tmdb.movie_details(tmdb_id)
    except TMDBError as exc:
        raise_tmdb_error(exc)


@router.get("/tv/{tmdb_id}", response_model=CatalogDetails)
async def tv_details(
    tmdb_id: int = Path(gt=0),
):
    try:
        return await tmdb.tv_details(tmdb_id)
    except TMDBError as exc:
        raise_tmdb_error(exc)


@router.get(
    "/tv/{tmdb_id}/season/{season_number}",
    response_model=SeasonDetails,
)
async def season_details(
    tmdb_id: int = Path(gt=0),
    season_number: int = Path(ge=0),
):
    try:
        return await tmdb.season_details(
            tmdb_id,
            season_number,
        )
    except TMDBError as exc:
        raise_tmdb_error(exc)
