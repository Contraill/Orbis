"""Owner authority is a credential, never a selected profile ID."""
import hashlib
import hmac
import secrets
from datetime import timedelta

from fastapi import Depends, Header, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from db.models.foundation import AdminSession, Installation
from db.models.profile import Profile, utc_now
from db.session import get_db


def installation(db: Session) -> Installation:
    db.execute(insert(Installation).values(id=1, locale="en-US", failed_logins=0).on_conflict_do_nothing())
    return db.get(Installation, 1)


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return f"scrypt${salt}${digest}"


def verify_password(password: str, encoded: str | None) -> bool:
    if not encoded:
        return False
    _, salt, expected = encoded.split("$")
    actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return hmac.compare_digest(actual, expected)


def issue_session(db: Session, owner_id: int) -> str:
    now = utc_now()
    db.execute(delete(AdminSession).where(AdminSession.expires_at <= now))
    # Keep a bounded number of browser sessions even during repeated logins.
    sessions = db.scalars(select(AdminSession).order_by(AdminSession.expires_at.desc())).all()
    for old in sessions[9:]:
        db.delete(old)
    token = secrets.token_urlsafe(32)
    db.add(AdminSession(token_hash=hashlib.sha256(token.encode()).hexdigest(), owner_id=owner_id, expires_at=now + timedelta(hours=8)))
    return token


def require_owner(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> Profile:
    if not authorization or not authorization.startswith("Bearer ") or len(authorization) > 128:
        raise HTTPException(401, "Owner authentication required")
    digest = hashlib.sha256(authorization[7:].encode()).hexdigest()
    session = db.get(AdminSession, digest)
    config = db.get(Installation, 1)
    if not session or session.expires_at <= utc_now() or not config or session.owner_id != config.owner_id:
        raise HTTPException(401, "Owner session expired or invalid")
    owner = db.get(Profile, session.owner_id)
    if not owner or not owner.is_owner:
        raise HTTPException(403, "Owner authorization required")
    return owner
