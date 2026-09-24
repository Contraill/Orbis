"""V1 additive error envelope. Legacy `detail` remains for existing clients."""
import re
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

CODES = {
    'Profile not found':'profile_not_found',
    'Profile name already exists':'profile_name_conflict',
    'Owner authentication required':'owner_authentication_required',
    'Owner session expired or invalid':'owner_session_invalid',
    'Owner authorization required':'owner_required',
    'Client session not found':'client_session_not_found',
    'Client session revoked':'client_session_revoked',
    'Playback source session not found':'playback_source_not_found',
    'Playback source has expired':'playback_source_expired',
    'Feed snapshot expired':'feed_snapshot_expired',
    'Feed cursor expired; restart the feed':'feed_cursor_expired',
    'Feed snapshot expired; restart the feed':'feed_snapshot_expired',
    'Profile activity changed; restart the feed':'feed_invalidated',
    'Cursor does not belong to this profile/surface/locale':'cursor_scope_mismatch',
    'Search cursor expired; start a new search':'search_cursor_expired',
    'Catalog cursor expired':'catalog_cursor_expired',
    'Cursor does not belong to this search':'cursor_scope_mismatch',
    'Cursor does not belong to this catalog query':'cursor_scope_mismatch',
    'Playback identity is not active for this client':'playback_identity_mismatch',
    'Playback source was replaced':'playback_source_replaced',
    'Source is not active for this client session':'playback_source_inactive',
    'Resolve playback before reporting a playing session':'playback_not_resolved',
    'Playback resource could not be loaded':'playback_upstream_unavailable',
    'Setup is already closed':'setup_closed',
    'Provider not registered':'provider_not_found',
    'Invalid owner credentials':'invalid_owner_credentials',
}
STATUS_CODES={400:'invalid_request',401:'authentication_required',403:'forbidden',404:'not_found',405:'method_not_allowed',409:'conflict',410:'expired',422:'validation_error',429:'rate_limited',500:'internal_error',502:'upstream_error',503:'unavailable'}


def safe_text(value):
    if value is None: return None
    value = re.sub(r'https?://[^\s\"\'<>]+','[upstream URL]',str(value))
    value = re.sub(r'(?i)(authorization|cookie|password|api[_-]?key|access[_-]?token|secret)([\"\']?\s*[:=]\s*)([^\r\n,;}]+)',r'\1\2[redacted]',value)
    return value[:2000]


def safe_value(value):
    if isinstance(value,str): return safe_text(value)
    if isinstance(value,list): return [safe_value(v) for v in value]
    if isinstance(value,dict): return {k:safe_value(v) for k,v in value.items() if k not in ('input','ctx')}
    return value


def error_response(status, detail, headers=None):
    detail=safe_value(detail)
    message=detail if isinstance(detail,str) else detail.get('message') if isinstance(detail,dict) else None
    code=detail.get('code') if isinstance(detail,dict) else CODES.get(detail) if isinstance(detail,str) else None
    code=code or STATUS_CODES.get(status,'request_failed')
    return JSONResponse(status_code=status,headers=headers,content={'detail':detail,'error':{'code':code,'message':message or code.replace('_',' '),'details':detail if not isinstance(detail,str) else None}})


async def http_error(request,exc: HTTPException):
    return error_response(exc.status_code,exc.detail,exc.headers)


async def validation_error(request,exc):
    fields=[{k:e[k] for k in ('type','loc','msg')} for e in exc.errors()]
    return error_response(422,fields)
