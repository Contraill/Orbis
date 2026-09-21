from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models.provider import ProviderEvent
from db.session import get_db
from providers.manager import (
    ProviderNotRegistered,
    ResolutionFailed,
    provider_manager,
)
from providers.registry import get_provider
from providers.schemas import (
    PlaybackResolution,
    ProviderAdminView,
    ProviderEventView,
    ProviderHealthCheckReport,
)


router = APIRouter(
    prefix="/api/admin/providers",
    tags=["admin-providers"],
)


class ProviderUpdate(BaseModel):
    enabled: bool | None = None
    priority: int | None = Field(
        default=None,
        ge=0,
        le=10000,
    )


def provider_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Provider not registered",
    )


def resolution_failed(exc: ResolutionFailed) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail={
            "message": str(exc),
            "attempts": [
                attempt.model_dump(mode="json")
                for attempt in exc.attempts
            ],
        },
    )


@router.get("", response_model=list[ProviderAdminView])
def list_providers(
    db: Session = Depends(get_db),
):
    return provider_manager.list_providers(db)


@router.patch(
    "/{provider_id}",
    response_model=ProviderAdminView,
)
def update_provider(
    provider_id: str,
    payload: ProviderUpdate,
    db: Session = Depends(get_db),
):
    if get_provider(provider_id) is None:
        raise provider_not_found()

    try:
        return provider_manager.update_provider(
            db,
            provider_id,
            enabled=payload.enabled,
            priority=payload.priority,
        )
    except ProviderNotRegistered:
        raise provider_not_found()


@router.post(
    "/{provider_id}/test",
    response_model=ProviderHealthCheckReport,
)
async def test_provider(
    provider_id: str,
    db: Session = Depends(get_db),
):
    if get_provider(provider_id) is None:
        raise provider_not_found()

    try:
        return await provider_manager.health_check(
            db,
            provider_id,
        )
    except ProviderNotRegistered:
        raise provider_not_found()


@router.get(
    "/{provider_id}/logs",
    response_model=list[ProviderEventView],
)
def provider_logs(
    provider_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    if get_provider(provider_id) is None:
        raise provider_not_found()

    return db.scalars(
        select(ProviderEvent)
        .where(ProviderEvent.provider_id == provider_id)
        .order_by(ProviderEvent.id.desc())
        .limit(limit)
    ).all()


@router.post(
    "/resolve-test/movie/{tmdb_id}",
    response_model=PlaybackResolution,
)
async def fallback_movie_test(
    tmdb_id: int = Path(gt=0),
    db: Session = Depends(get_db),
):
    try:
        return await provider_manager.resolve_movie(
            db,
            tmdb_id,
        )
    except ResolutionFailed as exc:
        raise resolution_failed(exc)


@router.post(
    "/resolve-test/tv/{tmdb_id}/season/{season}/episode/{episode}",
    response_model=PlaybackResolution,
)
async def fallback_episode_test(
    tmdb_id: int = Path(gt=0),
    season: int = Path(ge=0),
    episode: int = Path(gt=0),
    db: Session = Depends(get_db),
):
    try:
        return await provider_manager.resolve_episode(
            db,
            tmdb_id,
            season,
            episode,
        )
    except ResolutionFailed as exc:
        raise resolution_failed(exc)


@router.post(
    "/{provider_id}/resolve-test/movie/{tmdb_id}",
    response_model=PlaybackResolution,
)
async def provider_movie_test(
    provider_id: str,
    tmdb_id: int = Path(gt=0),
    db: Session = Depends(get_db),
):
    if get_provider(provider_id) is None:
        raise provider_not_found()

    try:
        return await provider_manager.resolve_movie(
            db,
            tmdb_id,
            provider_id=provider_id,
            force=True,
        )
    except ProviderNotRegistered:
        raise provider_not_found()
    except ResolutionFailed as exc:
        raise resolution_failed(exc)


@router.post(
    "/{provider_id}/resolve-test/tv/{tmdb_id}/season/{season}/episode/{episode}",
    response_model=PlaybackResolution,
)
async def provider_episode_test(
    provider_id: str,
    tmdb_id: int = Path(gt=0),
    season: int = Path(ge=0),
    episode: int = Path(gt=0),
    db: Session = Depends(get_db),
):
    if get_provider(provider_id) is None:
        raise provider_not_found()

    try:
        return await provider_manager.resolve_episode(
            db,
            tmdb_id,
            season,
            episode,
            provider_id=provider_id,
            force=True,
        )
    except ProviderNotRegistered:
        raise provider_not_found()
    except ResolutionFailed as exc:
        raise resolution_failed(exc)
