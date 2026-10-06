"""Isolated browser fixture, never imported by the production application."""
import os
from datetime import timedelta
from unittest.mock import patch

if os.environ.get("ORBIS_BROWSER_FIXTURE") != "1" or not os.environ.get("DATABASE_URL", "").startswith("sqlite:////tmp/"):
    raise RuntimeError("Browser fixture requires an explicitly isolated /tmp database")

from fastapi import Depends
from core.auth import require_owner
from db.base import Base
from db.models.profile import Profile, utc_now
from db.session import engine, SessionLocal
from main import app
from metadata.tmdb import TMDBClient
from playback.service import movie_identity, episode_identity, upsert_playback_state
from playback.schemas import PlaybackStateUpdate
from activity.service import record_progress

Base.metadata.create_all(engine)


async def mock_get(self, path, params=None):
    tr = self.locale == "tr-TR"
    def movie(n):
        return {"id": n, "media_type": "movie", "title": f"{'Film' if tr else 'Movie'} {n}",
                "original_title": f"Original {n}", "overview": "Fixture overview", "genres": [{"id": 1, "name": "Dram" if tr else "Drama"}]}
    if path.startswith("/search/") or path.startswith("/trending/"):
        return {"page": 1, "total_pages": 1, "results": [movie(n) for n in range(1, 7)]}
    if path.endswith(("/popular", "/recommendations", "/similar")):
        if path.startswith("/tv/"):
            return {"page": 1, "total_pages": 1, "results": [
                {"id": n, "name": f"{'Dizi' if tr else 'Series'} {n}", "original_name": f"Series {n}"} for n in range(50, 56)]}
        return {"page": 1, "total_pages": 1, "results": [movie(n) for n in range(1, 7)]}
    if "/season/" in path:
        return {"id": 500, "season_number": 1, "name": "Sezon 1" if tr else "Season 1", "episodes": [{"episode_number": n, "name": f"Episode {n}", "air_date": "2020-01-01"} for n in range(1, 4)]}
    if path.startswith("/tv/"):
        return {"id": int(path.split("/")[-1]), "name": "Dizi" if tr else "Series", "original_name": "Series", "number_of_seasons": 1}
    return movie(int(path.split("/")[-1]))


TMDBClient._get = mock_get


@app.post("/api/__fixture__/watch")
def evidence(owner: Profile = Depends(require_owner)):
    now = utc_now() - timedelta(minutes=10)
    with SessionLocal() as db:
        for identity in (movie_identity(1), episode_identity(50, 1, 1), episode_identity(50, 1, 2)):
            for position in (1, 16, 31, 46, 61, 76, 91):
                update = PlaybackStateUpdate(position_seconds=position, duration_seconds=600)
                with patch("activity.service.utc_now", return_value=now + timedelta(seconds=position)):
                    upsert_playback_state(db, owner.id, identity, update, record_activity=True)
    return {"ok": True}


def run():
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
