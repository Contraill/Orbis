from typing import Literal

from fastapi import Depends, HTTPException, Query
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from db.models.foundation import Installation, LocalizedMetadata
from db.models.profile import Profile, utc_now
from db.session import get_db


def preferred_locale(profile_id: int | None = Query(default=None, gt=0), locale: Literal["en-US", "tr-TR"] | None = None, db: Session = Depends(get_db)):
    if profile_id is not None:
        profile = db.get(Profile, profile_id)
        if not profile:
            raise HTTPException(404, "Profile not found")
        return profile.locale
    config = db.get(Installation, 1)
    return locale or (config.locale if config else "en-US")


def store_metadata(db, locale, item):
    data = item.model_dump(mode="json")
    if "series_tmdb_id" in data:
        key = f"tv:{data['series_tmdb_id']}:season:{data['season_number']}"
    else:
        key = f"{data['media_type']}:{data['tmdb_id']}"
    old = db.get(LocalizedMetadata, (key, locale))
    combined = {**(old.data if old else {}), **data}
    stmt = insert(LocalizedMetadata).values(content_key=key, locale=locale, data=combined, fetched_at=utc_now())
    db.execute(stmt.on_conflict_do_update(index_elements=["content_key", "locale"], set_={"data": combined, "fetched_at": utc_now()}))


def store_response(db, locale, response):
    for item in getattr(response, "results", [response]):
        store_metadata(db, locale, item)
    db.commit()
    return response
