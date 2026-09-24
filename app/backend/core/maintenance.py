"""Bounded disposable-state maintenance. Never deletes viewing/library records."""
from datetime import timedelta
from sqlalchemy import delete,select
from db.models.catalog import SearchCache
from db.models.foundation import AdminSession
from db.models.provider import ProviderEvent
from db.models.profile import utc_now
from client_sessions.service import cleanup

BATCH=1000
MAX_CACHE_ROWS=2048
MAX_EVENTS=10000


def trim_cache(db, keep_key=None):
    # SQLite write transactions serialize insertion/eviction. Recent cursors can
    # legitimately expire early under capacity pressure; clients restart on 410.
    keys=select(SearchCache.key).where(SearchCache.key != (keep_key or '')).order_by(SearchCache.expires_at.desc(),SearchCache.key).offset(MAX_CACHE_ROWS-1)
    db.execute(delete(SearchCache).where(SearchCache.key.in_(keys)))


def run(app):
    import logging
    from db.session import get_db
    from playback.source_sessions import source_sessions
    factory=app.dependency_overrides.get(get_db,get_db)
    gen=factory()
    try:
        maintain(next(gen))
        source_sessions.cleanup()
    except Exception as exc:
        logging.getLogger(__name__).warning('maintenance_failed type=%s',type(exc).__name__)
    finally:
        gen.close()


def maintain(db):
    now=utc_now()
    for model,key,expired in [(SearchCache,SearchCache.key,SearchCache.expires_at<=now),
        (AdminSession,AdminSession.token_hash,AdminSession.expires_at<=now),
        (ProviderEvent,ProviderEvent.id,ProviderEvent.created_at<now-timedelta(days=30))]:
        db.execute(delete(model).where(key.in_(select(key).where(expired).limit(BATCH))))
    for model,key,order,cap in [(SearchCache,SearchCache.key,SearchCache.expires_at.desc(),MAX_CACHE_ROWS),
        (ProviderEvent,ProviderEvent.id,ProviderEvent.id.desc(),MAX_EVENTS)]:
        db.execute(delete(model).where(key.in_(select(key).order_by(order,key).offset(cap).limit(BATCH))))
    cleanup(db)
    db.commit()
