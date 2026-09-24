from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from db.session import get_db
from db.models.profile import Profile, utc_now
from db.models.catalog import SearchCache
from api.library import profile
from recommendations.engine import HybridRecommender
from recommendations.feeds import feed
from recommendations.schemas import FeedPage, Surface
from core.auth import require_owner

router = APIRouter(prefix="/api/feeds/profiles/{profile_id}", tags=["feeds"])


def recommender():
    """Replace this dependency to swap ranking implementations, keeping feed APIs."""
    return HybridRecommender()


@router.get("/{surface}", response_model=FeedPage)
async def get_feed(surface: Surface, batch_size: int = Query(default=3, ge=1, le=5),
    cursor: str | None = Query(default=None, max_length=64),
    owner: Profile = Depends(profile), db: Session = Depends(get_db), engine=Depends(recommender)):
    return await feed(db, owner, surface, batch_size, cursor, engine)


@router.get("/diagnostics/{snapshot_id}",dependencies=[Depends(require_owner)])
def diagnostics(snapshot_id: str, owner: Profile = Depends(profile), db: Session = Depends(get_db)):
    snapshot = db.get(SearchCache, snapshot_id)
    if not snapshot or snapshot.expires_at <= utc_now() or snapshot.data.get("type") != "feed_snapshot":
        raise HTTPException(410, "Feed snapshot expired")
    if snapshot.data["scope"]["profile_id"] != owner.id:
        raise HTTPException(404, "Snapshot not found for this profile")
    return snapshot.data["diagnostics"]
