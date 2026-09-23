from typing import Literal
from fastapi import APIRouter, Depends, Path, Request, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from db.session import get_db
from db.models.profile import Profile, utc_now
from db.models.client_session import ContentMarkers
from core.auth import require_owner
from client_sessions.service import audience, playback_context
from playback.episodes import lifecycle, transition, enrich_catalog
from playback.schemas import EpisodeMarkers, PlaybackSession, EpisodeLifecycle
from playback.service import episode_identity, ProfileNotFoundError
from providers.manager import ResolutionFailed
from api.playback import _resolution_failed

router = APIRouter(prefix="/api/playback/profiles/{profile_id}/tv/{tmdb_id}/season/{season_number}/episode/{episode_number}", tags=["episode lifecycle"], dependencies=[Depends(playback_context)])
admin_router = APIRouter(prefix="/api/admin/episode-markers", dependencies=[Depends(require_owner)], tags=["episode markers"])


def identity(tmdb_id: int = Path(gt=0), season_number: int = Path(ge=0), episode_number: int = Path(gt=0)):
    return episode_identity(tmdb_id, season_number, episode_number)


@router.get("/lifecycle", response_model=EpisodeLifecycle)
async def get_lifecycle(profile_id: int, enrich: bool = False, current=Depends(identity), db: Session = Depends(get_db)):
    profile = db.get(Profile, profile_id)
    if not profile:
        raise HTTPException(404, "Profile not found")
    warning = await enrich_catalog(db, current, profile.locale) if enrich else None
    return {**lifecycle(db, profile_id, current), "warning": warning}


class Transition(BaseModel):
    direction: Literal["next", "previous"] = "next"
    prepared_source_session_id: str | None = Field(default=None, max_length=128)


@router.post("/prepare-next", response_model=PlaybackSession)
async def prepare_next(profile_id: int, current=Depends(identity), db: Session = Depends(get_db), client=Depends(audience)):
    try:
        return await transition(db, profile_id, current, "next", client, prepare=True)
    except ResolutionFailed as exc:
        raise _resolution_failed(exc)


@router.post("/transition", response_model=PlaybackSession)
async def transition_episode(payload: Transition, profile_id: int, current=Depends(identity), db: Session = Depends(get_db), client=Depends(audience)):
    try:
        return await transition(db, profile_id, current, payload.direction, client, prepared_id=payload.prepared_source_session_id)
    except ResolutionFailed as exc:
        raise _resolution_failed(exc)


class MarkerInput(EpisodeMarkers):
    source: str = Field(min_length=1, max_length=100)


@admin_router.put("/tv/{tmdb_id}/season/{season_number}/episode/{episode_number}")
def set_markers(payload: MarkerInput, current=Depends(identity), db: Session = Depends(get_db)):
    row = db.get(ContentMarkers, current.content_key)
    if row is None:
        row = ContentMarkers(content_key=current.content_key)
        db.add(row)
    row.markers = payload.model_dump(exclude={"source"})
    row.source, row.updated_at = payload.source, utc_now()
    db.commit()
    return {"markers": row.markers, "source": row.source}
