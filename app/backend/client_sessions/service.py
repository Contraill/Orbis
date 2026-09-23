from datetime import timedelta
from secrets import token_urlsafe
import re
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from db.session import get_db
from db.models.client_session import ClientSession
from db.models.profile import Profile, utc_now
from playback.capabilities import request_client
from playback.source_sessions import source_sessions

STALE_AFTER = timedelta(minutes=2)
RETENTION = timedelta(days=1)
MAX_SESSIONS = 256


def audience(request: Request, response: Response):
    value = request.cookies.get("playback_client", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,64}", value):
        value = token_urlsafe(24)
        response.set_cookie("playback_client", value, httponly=True, samesite="strict", max_age=21600)
    return value


def stop(row, state="stopped", revoke=True):
    if revoke:
        source_sessions.revoke_client(row.id)
    row.state, row.stopped_at = state, utc_now()
    row.current_playback, row.source_session_id, row.position_seconds = None, None, 0


def cleanup(db, now=None, reserve=0):
    now = now or utc_now()
    rows = db.scalars(select(ClientSession).order_by(ClientSession.last_seen.desc(), ClientSession.id)).all()
    for index, row in enumerate(rows):
        if row.last_seen < now - RETENTION or index >= MAX_SESSIONS - reserve:
            source_sessions.revoke_client(row.id)
            db.delete(row)
        elif row.last_seen < now - STALE_AFTER and row.state not in ("stopped", "stale", "revoked"):
            stop(row, "stale")
    db.flush()


def require(db, session_id, audience_value, profile_id=None):
    row = db.get(ClientSession, session_id)
    if not row or row.audience != audience_value or profile_id is not None and row.profile_id != profile_id:
        raise HTTPException(404, "Client session not found")
    if row.revoked_at:
        raise HTTPException(403, "Client session revoked")
    return row


def view(row):
    return {key: getattr(row, key) for key in ("id", "profile_id", "display_name", "client_type", "capabilities", "created_at", "last_seen", "state", "current_playback", "position_seconds", "started_at", "stopped_at", "revoked_at")}


async def playback_context(request: Request, db: Session = Depends(get_db)):
    session_id = request.headers.get("X-Orbis-Session")
    if not session_id:
        token = request_client.set(None)
        try:
            yield
        finally:
            request_client.reset(token)
        return
    cleanup(db)
    row = require(db, session_id, request.cookies.get("playback_client", ""), int(request.path_params["profile_id"]))
    ctx = {"id": row.id, "capabilities": row.capabilities, "current_playback": row.current_playback}
    db.commit()
    token = request_client.set(ctx)
    try:
        yield
        if ctx.get("resolved"):
            row = db.get(ClientSession, session_id, populate_existing=True)
            if not row or row.revoked_at:
                source_sessions.revoke_client(session_id)
            if row and not row.revoked_at:
                source, identity = ctx["resolved"]
                same_content = row.current_playback and row.current_playback.get("content_key") == identity["content_key"]
                previous_state = row.state
                if not same_content:
                    row.started_at, row.stopped_at = None, None
                row.current_playback = identity
                row.source_session_id = source.session_id
                row.state, row.last_seen = (previous_state if same_content and previous_state in ("playing", "paused") else "preparing"), utc_now()
                row.position_seconds = ctx.get("position", 0)
                db.commit()
        elif "position" in ctx:
            row = db.get(ClientSession, session_id, populate_existing=True)
            if row and not row.revoked_at:
                row.position_seconds, row.last_seen = ctx["position"], utc_now()
                if ctx.get("completed"):
                    stop(row, revoke=False)
                db.commit()
    finally:
        request_client.reset(token)
