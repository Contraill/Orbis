import hashlib
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from core.auth import hash_password, installation, issue_session, require_owner, verify_password
from db.models.foundation import AdminSession, Installation
from db.models.profile import Profile, utc_now
from db.session import get_db

router = APIRouter(prefix="/api/setup", tags=["setup"])


class LocaleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    locale: Literal["en-US", "tr-TR"]


class BootstrapInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=80)
    password: SecretStr = Field(min_length=12, max_length=128)
    locale: Literal["en-US", "tr-TR"] | None = None


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: SecretStr = Field(min_length=1, max_length=128)


@router.get("")
def setup_status(db: Session = Depends(get_db)):
    config = installation(db)
    db.commit()
    return {"locale": config.locale, "setup_required": config.owner_id is None,
            "owner_id": config.owner_id, "owner_password_configured": bool(config.password_hash)}


@router.put("/locale")
def set_locale(payload: LocaleInput, db: Session = Depends(get_db)):
    installation(db)
    result = db.execute(update(Installation).where(Installation.id == 1, Installation.owner_id.is_(None)).values(locale=payload.locale))
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "Setup is already closed")
    db.commit()
    return {"locale": payload.locale}


@router.post("/owner", status_code=201)
def bootstrap(payload: BootstrapInput, db: Session = Depends(get_db)):
    # Hash outside the write transaction; the conditional write below serializes claims.
    encoded = hash_password(payload.password.get_secret_value())
    config = installation(db)
    if config.owner_id is not None or db.scalar(select(Profile.id).limit(1)) is not None:
        db.rollback()
        raise HTTPException(409, "Setup is already closed")
    profile = Profile(name=payload.name, avatar_seed=payload.name, locale=payload.locale or config.locale, is_owner=True)
    db.add(profile)
    db.flush()
    result = db.execute(update(Installation).where(Installation.id == 1, Installation.owner_id.is_(None)).values(owner_id=profile.id, password_hash=encoded))
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "Setup is already closed")
    token = issue_session(db, profile.id)
    db.commit()
    return {"owner_id": profile.id, "token": token}


@router.post("/login")
def login(payload: LoginInput, db: Session = Depends(get_db)):
    config = installation(db)  # write lock also serializes the lockout counter
    now = utc_now()
    if config.locked_until and config.locked_until > now:
        raise HTTPException(429, "Try again later")
    if not config.owner_id or not verify_password(payload.password.get_secret_value(), config.password_hash):
        config.failed_logins += 1
        if config.failed_logins >= 5:
            config.locked_until = now + timedelta(minutes=5)
            config.failed_logins = 0
        db.commit()
        raise HTTPException(401, "Invalid owner credentials")
    config.failed_logins = 0
    config.locked_until = None
    token = issue_session(db, config.owner_id)
    db.commit()
    return {"owner_id": config.owner_id, "token": token}


@router.get("/session")
def session(owner: Profile = Depends(require_owner)):
    return {"owner_id": owner.id}


@router.post("/logout")
def logout(authorization: str = Header(), owner: Profile = Depends(require_owner), db: Session = Depends(get_db)):
    session = db.get(AdminSession, hashlib.sha256(authorization[7:].encode()).hexdigest())
    db.delete(session)
    db.commit()
    return {"ok": True}
