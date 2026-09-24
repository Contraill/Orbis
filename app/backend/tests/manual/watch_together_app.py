"""Offline smoke fixture, never a production entrypoint.

Run after migrations with DATABASE_URL=sqlite:////tmp/orbis-watch-smoke.db.
PYTHONPATH must include /app/tests and /app/tests/manual.
"""
import os
assert os.environ.get('DATABASE_URL') == 'sqlite:////tmp/orbis-watch-smoke.db', 'Only the disposable smoke database is allowed'
from unittest.mock import patch
from main import app
from db.session import SessionLocal
from db.models.profile import Profile
from db.models.foundation import Installation
from metadata.localization import store_metadata
from metadata.schemas import CatalogDetails,SeasonDetails,EpisodeSummary
from playback.service import upsert_playback_state,episode_identity
from playback.schemas import PlaybackStateUpdate
from test_playback_hardening import SequencedProvider,source

providers = [SequencedProvider('smoke-a',1,[[source('smoke-a','moly',protocol='http',quality='900p')]]),
             SequencedProvider('smoke-b',2,[[source('smoke-b','dbx',protocol='http',quality='720p')]])]
mapping={p.id:p for p in providers}
patch('providers.manager.all_providers',return_value=mapping).start()
patch('providers.manager.get_provider',side_effect=mapping.get).start()
with SessionLocal() as db:
    if not db.get(Profile,1):
        db.add_all([Profile(id=1,name='Smoke A'),Profile(id=2,name='Smoke B')])
        db.commit()
    # Browser fixture setup is complete; this does not grant owner credentials.
    if not db.get(Installation,1):
        db.add(Installation(id=1,owner_id=1))
    else:
        db.get(Installation,1).owner_id=1
    db.get(Profile,1).is_owner=True
    upsert_playback_state(db,2,episode_identity(42,1,1),PlaybackStateUpdate(preferred_provider_id='smoke-b'))
    store_metadata(db,'en-US',CatalogDetails(tmdb_id=42,media_type='tv',title='Offline series',status='Ended',seasons=[
        {'tmdb_id':1,'season_number':1,'name':'First','episode_count':2},
        {'tmdb_id':2,'season_number':2,'name':'Last','episode_count':1}]))
    for number,count in [(1,2),(2,1)]:
        store_metadata(db,'en-US',SeasonDetails(series_tmdb_id=42,season_tmdb_id=number,season_number=number,name='Season',episodes=[
            EpisodeSummary(tmdb_id=number*10+i,episode_number=i,name='Episode',air_date='2020-01-01') for i in range(1,count+1)]))
    db.commit()
