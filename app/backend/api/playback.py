from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.orm import Session

from db.session import get_db
from playback.schemas import (
    PlaybackFailoverRequest,
    PlaybackSession,
    PlaybackStateUpdate,
    PlaybackStateView,
)
from playback.service import (
    ContentIdentity,
    ProfileNotFoundError,
    episode_identity,
    get_playback_state,
    movie_identity,
    playback_service,
    state_view,
    upsert_playback_state,
)
from providers.manager import ResolutionFailed


router = APIRouter(
    prefix="/api/playback/profiles/{profile_id}",
    tags=["playback"],
)


def _profile_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Profile not found",
    )


def _resolution_failed(exc: ResolutionFailed) -> HTTPException:
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


def _get_state(
    db: Session,
    profile_id: int,
    identity: ContentIdentity,
) -> PlaybackStateView | None:
    try:
        state = get_playback_state(
            db,
            profile_id,
            identity,
        )
    except ProfileNotFoundError:
        raise _profile_not_found()

    return state_view(state) if state is not None else None


def _put_state(
    db: Session,
    profile_id: int,
    identity: ContentIdentity,
    payload: PlaybackStateUpdate,
) -> PlaybackStateView:
    try:
        return state_view(
            upsert_playback_state(
                db,
                profile_id,
                identity,
                payload,
            )
        )
    except ProfileNotFoundError:
        raise _profile_not_found()


async def _resolve(
    db: Session,
    profile_id: int,
    identity: ContentIdentity,
) -> PlaybackSession:
    try:
        return await playback_service.resolve(
            db,
            profile_id,
            identity,
        )
    except ProfileNotFoundError:
        raise _profile_not_found()
    except ResolutionFailed as exc:
        raise _resolution_failed(exc)


async def _failover(
    db: Session,
    profile_id: int,
    identity: ContentIdentity,
    payload: PlaybackFailoverRequest,
) -> PlaybackSession:
    update = PlaybackStateUpdate(
        **payload.model_dump(
            exclude={
                "failed_provider_id",
                "last_provider_id",
            }
        ),
        last_provider_id=payload.failed_provider_id,
    )

    try:
        upsert_playback_state(
            db,
            profile_id,
            identity,
            update,
        )
        return await playback_service.resolve(
            db,
            profile_id,
            identity,
            excluded_provider_ids={
                payload.failed_provider_id
            },
        )
    except ProfileNotFoundError:
        raise _profile_not_found()
    except ResolutionFailed as exc:
        raise _resolution_failed(exc)


@router.get(
    "/movie/{tmdb_id}/state",
    response_model=PlaybackStateView | None,
)
def get_movie_state(
    profile_id: int = Path(gt=0),
    tmdb_id: int = Path(gt=0),
    db: Session = Depends(get_db),
):
    return _get_state(
        db,
        profile_id,
        movie_identity(tmdb_id),
    )


@router.put(
    "/movie/{tmdb_id}/state",
    response_model=PlaybackStateView,
)
def put_movie_state(
    payload: PlaybackStateUpdate,
    profile_id: int = Path(gt=0),
    tmdb_id: int = Path(gt=0),
    db: Session = Depends(get_db),
):
    return _put_state(
        db,
        profile_id,
        movie_identity(tmdb_id),
        payload,
    )


@router.post(
    "/movie/{tmdb_id}/resolve",
    response_model=PlaybackSession,
)
async def resolve_movie(
    profile_id: int = Path(gt=0),
    tmdb_id: int = Path(gt=0),
    db: Session = Depends(get_db),
):
    return await _resolve(
        db,
        profile_id,
        movie_identity(tmdb_id),
    )


@router.post(
    "/movie/{tmdb_id}/failover",
    response_model=PlaybackSession,
)
async def failover_movie(
    payload: PlaybackFailoverRequest,
    profile_id: int = Path(gt=0),
    tmdb_id: int = Path(gt=0),
    db: Session = Depends(get_db),
):
    return await _failover(
        db,
        profile_id,
        movie_identity(tmdb_id),
        payload,
    )


def _episode_identity(
    tmdb_id: int,
    season_number: int,
    episode_number: int,
) -> ContentIdentity:
    return episode_identity(
        tmdb_id,
        season_number,
        episode_number,
    )


@router.get(
    "/tv/{tmdb_id}/season/{season_number}/episode/{episode_number}/state",
    response_model=PlaybackStateView | None,
)
def get_episode_state(
    profile_id: int = Path(gt=0),
    tmdb_id: int = Path(gt=0),
    season_number: int = Path(ge=0),
    episode_number: int = Path(gt=0),
    db: Session = Depends(get_db),
):
    return _get_state(
        db,
        profile_id,
        _episode_identity(
            tmdb_id,
            season_number,
            episode_number,
        ),
    )


@router.put(
    "/tv/{tmdb_id}/season/{season_number}/episode/{episode_number}/state",
    response_model=PlaybackStateView,
)
def put_episode_state(
    payload: PlaybackStateUpdate,
    profile_id: int = Path(gt=0),
    tmdb_id: int = Path(gt=0),
    season_number: int = Path(ge=0),
    episode_number: int = Path(gt=0),
    db: Session = Depends(get_db),
):
    return _put_state(
        db,
        profile_id,
        _episode_identity(
            tmdb_id,
            season_number,
            episode_number,
        ),
        payload,
    )


@router.post(
    "/tv/{tmdb_id}/season/{season_number}/episode/{episode_number}/resolve",
    response_model=PlaybackSession,
)
async def resolve_episode(
    profile_id: int = Path(gt=0),
    tmdb_id: int = Path(gt=0),
    season_number: int = Path(ge=0),
    episode_number: int = Path(gt=0),
    db: Session = Depends(get_db),
):
    return await _resolve(
        db,
        profile_id,
        _episode_identity(
            tmdb_id,
            season_number,
            episode_number,
        ),
    )


@router.post(
    "/tv/{tmdb_id}/season/{season_number}/episode/{episode_number}/failover",
    response_model=PlaybackSession,
)
async def failover_episode(
    payload: PlaybackFailoverRequest,
    profile_id: int = Path(gt=0),
    tmdb_id: int = Path(gt=0),
    season_number: int = Path(ge=0),
    episode_number: int = Path(gt=0),
    db: Session = Depends(get_db),
):
    return await _failover(
        db,
        profile_id,
        _episode_identity(
            tmdb_id,
            season_number,
            episode_number,
        ),
        payload,
    )
