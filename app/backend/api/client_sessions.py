from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from secrets import token_urlsafe
from db.session import get_db
from db.models.client_session import ClientSession
from db.models.profile import Profile, utc_now
from client_sessions.service import audience, cleanup, require, stop, view
from playback.capabilities import ClientCapabilities
from playback.source_sessions import source_sessions, SourceSessionNotFound, SourceSessionScopeError
from core.auth import require_owner

router = APIRouter(tags=["client sessions"])


class CreateSession(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile_id: int = Field(gt=0)
    display_name: str = Field(min_length=1, max_length=100)
    client_type: Literal["web", "mobile", "tizen", "webos", "other"] = "web"
    capabilities: ClientCapabilities | None = None


class Heartbeat(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: Literal["idle", "playing", "paused", "stopped"]
    position_seconds: float = Field(default=0, ge=0, allow_inf_nan=False)
    source_session_id: str | None = Field(default=None, max_length=128)
    capabilities: ClientCapabilities | None = None


@router.post("/api/sessions", status_code=201)
def create(payload: CreateSession, db: Session = Depends(get_db), client: str = Depends(audience)):
    if not db.get(Profile, payload.profile_id):
        raise HTTPException(404, "Profile not found")
    cleanup(db, reserve=1)
    row = ClientSession(id=token_urlsafe(32), profile_id=payload.profile_id, audience=client,
        display_name=payload.display_name, client_type=payload.client_type,
        capabilities=payload.capabilities.model_dump() if payload.capabilities is not None else None)
    db.add(row)
    db.commit()
    return view(row)


@router.get("/api/sessions/{session_id}")
def current(session_id: str, request: Request, db: Session = Depends(get_db)):
    cleanup(db)
    row = require(db, session_id, request.cookies.get("playback_client", ""))
    db.commit()
    return view(row)


@router.patch("/api/sessions/{session_id}")
def update(session_id: str, payload: Heartbeat, request: Request, db: Session = Depends(get_db)):
    cleanup(db)
    row = require(db, session_id, request.cookies.get("playback_client", ""))
    if payload.state in ("playing", "paused"):
        try:
            source = source_sessions.get(payload.source_session_id or row.source_session_id or "", profile_id=row.profile_id)
        except (SourceSessionNotFound, SourceSessionScopeError):
            raise HTTPException(409, "Resolve playback before reporting a playing session")
        if source.context.get("client_session_id") != row.id or source.context.get("preparation"):
            raise HTTPException(409, "Source is not active for this client session")
        if source.session_id != row.source_session_id:
            raise HTTPException(409, "Playback source was replaced")
        if payload.state == "playing" and row.started_at is None:
            row.started_at = utc_now()
        row.state, row.position_seconds = payload.state, payload.position_seconds
    else:
        if payload.source_session_id and payload.source_session_id != row.source_session_id:
            raise HTTPException(409, "Playback source was replaced")
        stop(row, payload.state)
    if "capabilities" in payload.model_fields_set:
        row.capabilities = payload.capabilities.model_dump() if payload.capabilities else None
    row.last_seen = utc_now()
    db.commit()
    return view(row)


@router.delete("/api/sessions/{session_id}")
def revoke_own(session_id: str, request: Request, db: Session = Depends(get_db)):
    row = require(db, session_id, request.cookies.get("playback_client", ""))
    stop(row, "revoked")
    row.revoked_at = utc_now()
    db.commit()
    return {"ok": True}


@router.get("/api/admin/sessions", dependencies=[Depends(require_owner)])
def admin_list(db: Session = Depends(get_db), limit: int = Query(default=64, ge=1, le=256)):
    cleanup(db)
    rows = db.scalars(select(ClientSession).order_by(ClientSession.last_seen.desc(), ClientSession.id).limit(limit)).all()
    db.commit()
    return [view(row) for row in rows]


@router.delete("/api/admin/sessions/{session_id}", dependencies=[Depends(require_owner)])
def admin_revoke(session_id: str, db: Session = Depends(get_db)):
    row = db.get(ClientSession, session_id)
    if not row:
        raise HTTPException(404, "Client session not found")
    stop(row, "revoked")
    row.revoked_at = utc_now()
    db.commit()
    return {"ok": True}
