from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from activity.service import continue_watching, metadata, progress_rows, recommendation_features, restart
from db.models.foundation import LibraryIntent, ViewingProgress
from core.auth import require_owner
from db.models.profile import Profile, utc_now
from db.session import get_db
from playback.service import ContentIdentity

router = APIRouter(prefix="/api/library/profiles/{profile_id}", tags=["library"])
Filter = Literal["all", "movie", "tv"]


def profile(profile_id: int, db: Session = Depends(get_db)):
    row = db.get(Profile, profile_id)
    if not row:
        raise HTTPException(404, "Profile not found")
    return row


class ItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    media_type: Literal["movie", "tv"]
    tmdb_id: int = Field(gt=0)


class IntentInput(ItemInput):
    enabled: bool


class RestartInput(ItemInput):
    season_number: int | None = Field(default=None, ge=0)
    episode_number: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def identity(self):
        ContentIdentity(self.media_type, self.tmdb_id, self.season_number, self.episode_number).content_key
        return self


def intent_row(db, profile_id, item):
    db.execute(insert(LibraryIntent).values(profile_id=profile_id, media_type=item.media_type, tmdb_id=item.tmdb_id,
        in_my_list=False, not_interested=False, hidden_watched_seconds=0).on_conflict_do_nothing())
    return db.get(LibraryIntent, (profile_id, item.media_type, item.tmdb_id))


@router.get("/continue")
def get_continue(kind: Filter = "all", owner: Profile = Depends(profile), db: Session = Depends(get_db)):
    return continue_watching(db, owner, kind)


@router.post("/continue/hide")
def hide(item: ItemInput, owner: Profile = Depends(profile), db: Session = Depends(get_db)):
    row = intent_row(db, owner.id, item)
    row.hidden_at = utc_now()
    from sqlalchemy import func
    row.hidden_watched_seconds = db.scalar(select(func.coalesce(func.sum(ViewingProgress.watched_seconds),0)).where(
        ViewingProgress.profile_id==owner.id,ViewingProgress.media_type==item.media_type,ViewingProgress.tmdb_id==item.tmdb_id))
    db.commit()
    return {"ok": True}


@router.post("/restart")
def start_over(item: RestartInput, owner: Profile = Depends(profile), db: Session = Depends(get_db)):
    restart(db, owner.id, ContentIdentity(**item.model_dump()))
    db.commit()
    return {"ok": True}


@router.get("/history")
def history(owner: Profile = Depends(profile), db: Session = Depends(get_db), limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0)):
    return [{"content_key": p.content_key, "media_type": p.media_type, "tmdb_id": p.tmdb_id,
        "season_number": p.season_number, "episode_number": p.episode_number,
        "started_at": p.started_at, "last_watched_at": p.last_watched_at,
        "watched_seconds": p.watched_seconds, "meaningful": p.watched_seconds >= 60,
        "completions": p.completions, "rewatches": p.rewatches,
        "metadata": metadata(db, p.media_type, p.tmdb_id, owner.locale)} for p in db.scalars(select(ViewingProgress).where(ViewingProgress.profile_id==owner.id).order_by(ViewingProgress.last_watched_at.desc(),ViewingProgress.content_key).offset(offset).limit(limit))]


@router.get("/my-list")
def my_list(kind: Filter = "all", owner: Profile = Depends(profile), db: Session = Depends(get_db)):
    query = select(LibraryIntent).where(LibraryIntent.profile_id == owner.id, LibraryIntent.in_my_list.is_(True))
    if kind != "all":
        query = query.where(LibraryIntent.media_type == kind)
    return [{"media_type": i.media_type, "tmdb_id": i.tmdb_id, "listed_at": i.listed_at,
        "metadata": metadata(db, i.media_type, i.tmdb_id, owner.locale)} for i in db.scalars(query.order_by(LibraryIntent.listed_at.desc()))]


@router.put("/my-list")
def set_my_list(item: IntentInput, owner: Profile = Depends(profile), db: Session = Depends(get_db)):
    row = intent_row(db, owner.id, item)
    if item.enabled and not row.in_my_list:
        row.listed_at = utc_now()
    row.in_my_list = item.enabled
    db.commit()
    return {"ok": True}


@router.put("/not-interested")
def set_negative(item: IntentInput, owner: Profile = Depends(profile), db: Session = Depends(get_db)):
    row = intent_row(db, owner.id, item)
    row.not_interested, row.feedback_at = item.enabled, utc_now()
    db.commit()
    return {"ok": True}


@router.get("/signals",dependencies=[Depends(require_owner)])
def signals(owner: Profile = Depends(profile), db: Session = Depends(get_db)):
    return recommendation_features(db, owner)
