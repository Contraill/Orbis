import asyncio
import re
from secrets import token_urlsafe

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response, status
from sqlalchemy.orm import Session

from db.session import get_db
from playback.schemas import (
    PlaybackChoices,
    PlaybackFailoverRequest,
    PlaybackRefreshRequest,
    PlaybackRecoverRequest,
    PlaybackSession,
    PlaybackStateUpdate,
    PlaybackStateView,
    PlaybackTransitionRequest,
)
from playback.service import (
    ContentIdentity,
    ProfileNotFoundError,
    episode_identity,
    get_playback_state,
    list_playback_states,
    movie_identity,
    playback_service,
    state_view,
    upsert_playback_state,
)
from playback.source_sessions import (
    SourceSessionNotFound,
    SourceSessionScopeError,
    source_sessions,
)
from providers.manager import ResolutionFailed
from providers.source_policy import source_expiry_status
from playback.delivery import DeliveryUnavailable, delivery_broker
from playback.choices import ranked_choices, set_session_choices


router = APIRouter(
    prefix="/api/playback/profiles/{profile_id}",
    tags=["playback"],
)


def _audience(request: Request, response: Response) -> str:
    value = request.cookies.get("playback_client", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,64}", value):
        value = token_urlsafe(24)
        response.set_cookie("playback_client", value, httponly=True, samesite="strict", max_age=21600)
    return value


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
                record_activity=True,
            )
        )
    except ProfileNotFoundError:
        raise _profile_not_found()


async def _resolve(
    db: Session,
    profile_id: int,
    identity: ContentIdentity,
    audience: str = "",
) -> PlaybackSession:
    try:
        return await playback_service.resolve(
            db,
            profile_id,
            identity,
            audience=audience,
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
    audience: str = "",
) -> PlaybackSession:
    return await _continue_playback(
        db,
        profile_id,
        identity,
        payload,
        current_provider_id=payload.failed_provider_id,
        excluded_provider_ids={payload.failed_provider_id},
        audience=audience,
    )


async def _continue_playback(
    db: Session,
    profile_id: int,
    identity: ContentIdentity,
    payload: PlaybackTransitionRequest,
    *,
    current_provider_id: str,
    excluded_provider_ids: set[str] | None = None,
    require_healthy_source: bool = False,
    audience: str = "",
) -> PlaybackSession:
    update = PlaybackStateUpdate(
        **payload.model_dump(
            exclude_unset=True,
            exclude={
                "failed_provider_id",
                "source_session_id",
                "last_provider_id",
                "preferred_audio_track_id",
                "preferred_subtitle_track_id",
                "failure",
            }
        ),
        last_provider_id=current_provider_id,
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
            excluded_provider_ids=excluded_provider_ids,
            require_healthy_source=require_healthy_source,
            preferred_audio_track_id=(
                payload.preferred_audio_track_id
            ),
            preferred_subtitle_track_id=(
                payload.preferred_subtitle_track_id
            ),
            audience=audience,
        )
    except ProfileNotFoundError:
        raise _profile_not_found()
    except ResolutionFailed as exc:
        raise _resolution_failed(exc)


async def _refresh(
    db: Session,
    profile_id: int,
    identity: ContentIdentity,
    payload: PlaybackRefreshRequest,
) -> PlaybackSession:
    try:
        source_session = source_sessions.get(
            payload.source_session_id,
            profile_id=profile_id,
            content_key=identity.content_key,
        )
    except (SourceSessionNotFound, SourceSessionScopeError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Playback source session not found",
        )

    return await _continue_playback(
        db,
        profile_id,
        identity,
        payload,
        current_provider_id=source_session.source.provider_id,
        require_healthy_source=True,
        audience=source_session.audience,
    )


async def _recover(db, profile_id, identity, payload):
    try:
        source_session = source_sessions.get(
            payload.source_session_id, profile_id=profile_id,
            content_key=identity.content_key,
        )
    except (SourceSessionNotFound, SourceSessionScopeError):
        raise HTTPException(404, "Playback source session not found")
    if source_expiry_status(source_session.source) == "expired":
        return await _refresh(db, profile_id, identity, payload)
    try:
        update = PlaybackStateUpdate(**payload.model_dump(include=set(PlaybackStateUpdate.model_fields), exclude_unset=True))
        update.last_provider_id = source_session.source.provider_id
        state = upsert_playback_state(db, profile_id, identity, update)
        async with asyncio.timeout(30):
            replacement = await delivery_broker.recover(source_session, payload.failure)
        return playback_service.session_view(
            state, replacement, [], payload.preferred_audio_track_id,
            payload.preferred_subtitle_track_id,
        )
    except ProfileNotFoundError:
        raise _profile_not_found()
    except (DeliveryUnavailable, TimeoutError):
        alternative = await playback_service.next_source(
            state, source_session, payload.preferred_audio_track_id,
            payload.preferred_subtitle_track_id,
        )
        if alternative is not None:
            return alternative
        return await _continue_playback(
            db, profile_id, identity, payload,
            current_provider_id=source_session.source.provider_id,
            excluded_provider_ids=set(source_session.context.get("excluded_provider_ids", ())) | {source_session.source.provider_id},
            audience=source_session.audience,
        )


async def _choose(db, profile_id, identity, payload):
    try:
        previous = source_sessions.get(payload.source_session_id, profile_id=profile_id, content_key=identity.content_key)
    except (SourceSessionNotFound, SourceSessionScopeError):
        raise HTTPException(404, "Playback source session not found")
    try:
        update = PlaybackStateUpdate(**payload.model_dump(include=set(PlaybackStateUpdate.model_fields), exclude_unset=True))
        update.last_provider_id = previous.source.provider_id
        state = upsert_playback_state(db, profile_id, identity, update)
        if state.preferred_provider_id and state.preferred_provider_id != previous.source.provider_id:
            return await _resolve(db, profile_id, identity, previous.audience)
        candidates = ranked_choices(previous.context.get("sources", [previous.source]), state)
        if not candidates:
            return await _resolve(db, profile_id, identity, previous.audience)
        if candidates[0].url == previous.source.url:
            return playback_service.session_view(state, previous, [], payload.preferred_audio_track_id, payload.preferred_subtitle_track_id)
        replacement = delivery_broker.issue(profile_id, identity.content_key, candidates[0], previous.audience)
        await set_session_choices(replacement, candidates, previous.context.get("choices", PlaybackChoices()).providers, state)
        replacement.context["excluded_provider_ids"] = previous.context.get("excluded_provider_ids", set())
        return playback_service.session_view(state, replacement, [])
    except ProfileNotFoundError:
        raise _profile_not_found()


@router.post("/movie/{tmdb_id}/choices", response_model=PlaybackSession)
async def choose_movie(payload: PlaybackRefreshRequest, profile_id: int = Path(gt=0), tmdb_id: int = Path(gt=0), db: Session = Depends(get_db)):
    return await _choose(db, profile_id, movie_identity(tmdb_id), payload)


@router.post("/tv/{tmdb_id}/season/{season_number}/episode/{episode_number}/choices", response_model=PlaybackSession)
async def choose_episode(payload: PlaybackRefreshRequest, profile_id: int = Path(gt=0), tmdb_id: int = Path(gt=0), season_number: int = Path(ge=0), episode_number: int = Path(gt=0), db: Session = Depends(get_db)):
    return await _choose(db, profile_id, episode_identity(tmdb_id, season_number, episode_number), payload)


@router.get(
    "/states",
    response_model=list[PlaybackStateView],
)
def get_profile_playback_states(
    profile_id: int = Path(gt=0),
    db: Session = Depends(get_db),
):
    try:
        return [
            state_view(state)
            for state in list_playback_states(db, profile_id)
        ]
    except ProfileNotFoundError:
        raise _profile_not_found()


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
    audience: str = Depends(_audience),
):
    return await _resolve(
        db,
        profile_id,
        movie_identity(tmdb_id),
        audience,
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
    audience: str = Depends(_audience),
):
    return await _failover(
        db,
        profile_id,
        movie_identity(tmdb_id),
        payload,
        audience,
    )


@router.post(
    "/movie/{tmdb_id}/refresh",
    response_model=PlaybackSession,
)
async def refresh_movie(
    payload: PlaybackRefreshRequest,
    profile_id: int = Path(gt=0),
    tmdb_id: int = Path(gt=0),
    db: Session = Depends(get_db),
):
    return await _refresh(
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
    audience: str = Depends(_audience),
):
    return await _resolve(
        db,
        profile_id,
        _episode_identity(
            tmdb_id,
            season_number,
            episode_number,
        ),
        audience,
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
    audience: str = Depends(_audience),
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
        audience,
    )


@router.post(
    "/tv/{tmdb_id}/season/{season_number}/episode/{episode_number}/refresh",
    response_model=PlaybackSession,
)
async def refresh_episode(
    payload: PlaybackRefreshRequest,
    profile_id: int = Path(gt=0),
    tmdb_id: int = Path(gt=0),
    season_number: int = Path(ge=0),
    episode_number: int = Path(gt=0),
    db: Session = Depends(get_db),
):
    return await _refresh(
        db,
        profile_id,
        _episode_identity(
            tmdb_id,
            season_number,
            episode_number,
        ),
        payload,
    )


@router.post("/movie/{tmdb_id}/recover", response_model=PlaybackSession)
async def recover_movie(
    payload: PlaybackRecoverRequest, profile_id: int = Path(gt=0),
    tmdb_id: int = Path(gt=0), db: Session = Depends(get_db),
):
    return await _recover(db, profile_id, movie_identity(tmdb_id), payload)


@router.post("/tv/{tmdb_id}/season/{season_number}/episode/{episode_number}/recover", response_model=PlaybackSession)
async def recover_episode(
    payload: PlaybackRecoverRequest, profile_id: int = Path(gt=0),
    tmdb_id: int = Path(gt=0), season_number: int = Path(ge=0),
    episode_number: int = Path(gt=0), db: Session = Depends(get_db),
):
    return await _recover(db, profile_id, episode_identity(tmdb_id, season_number, episode_number), payload)
