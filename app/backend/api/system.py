"""Safe owner diagnostics; no environment values, URLs or session credentials."""
from fastapi import APIRouter,Depends
from core.auth import require_owner
from core.config import get_settings
from core.maintenance import MAX_CACHE_ROWS,MAX_EVENTS
from watch_together.domain import rooms
router=APIRouter(prefix='/api/admin',tags=['system'],dependencies=[Depends(require_owner)])

@router.get('/system')
def system():
    return {'version':'1.0.0','api_version':'v1','build_id':get_settings().build_id,'single_worker':True,'rooms_survive_restart':False,
        'maintenance_seconds':60,'max_search_feed_cache_rows':MAX_CACHE_ROWS,'max_recent_provider_events':MAX_EVENTS}

@router.get('/watch-together/rooms')
def room_diagnostics():
    with rooms.lock:
        return [{key:value for key,value in rooms.snapshot(room).items() if key != 'join_code'} for room in rooms.rooms.values()]
