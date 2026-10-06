from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing import Literal
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db.models.profile import Profile
from db.session import get_db
from core.auth import require_owner
from db.models.foundation import Installation


router = APIRouter(prefix="/api/profiles", tags=["profiles"])


class Seed(BaseModel):
    model_config = ConfigDict(extra="forbid")
    media_type: Literal["movie", "tv"]
    tmdb_id: int = Field(gt=0)


class AvatarConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    shape: Literal["round", "organic", "boxy", "capsule", "nub", "cloud", "droplet", "hexagon", "sun", "triangle"] | None = None
    face_preset: Literal["soft", "wide", "tall", "big_eyes", "compact"] | None = None
    expression: Literal["idle", "happy", "sad", "mad", "surprised", "wink", "sleepy", "smug", "unsure", "scared", "love", "shy", "sick", "thinking"] | None = None
    hue: int | None = Field(default=None, ge=0, lt=360)
    tone: float | Literal["pale", "mid", "deep", "bright"] | None = None

    @field_validator("tone")
    @classmethod
    def valid_tone(cls, value):
        if isinstance(value, float) and not 0 <= value < 1:
            raise ValueError("Avatar tone must be between 0 and 1")
        return value


class ProfilePreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    avatar_seed: str | None = Field(default=None, min_length=1, max_length=255)
    avatar_config: AvatarConfig | None = None
    locale: Literal["en-US", "tr-TR"] | None = None
    preferred_audio_language: str | None = Field(default=None, max_length=32, pattern=r"^[a-zA-Z]{2,3}(-[a-zA-Z0-9]{2,8})*$")
    preferred_subtitle_language: str | None = Field(default=None, max_length=32, pattern=r"^[a-zA-Z]{2,3}(-[a-zA-Z0-9]{2,8})*$")
    subtitles_enabled: bool = False
    autoplay_next_episode: bool = True
    trailer_muted: bool = True
    onboarding_seeds: list[Seed] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def unique_seeds(self):
        if len({(s.media_type, s.tmdb_id) for s in self.onboarding_seeds}) != len(self.onboarding_seeds):
            raise ValueError("Onboarding selections must be unique")
        for name in ("avatar_seed", "locale"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class ProfileCreate(ProfilePreferences):
    name: str = Field(min_length=1, max_length=80)
    avatar: str | None = Field(default=None, max_length=255)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Profile name cannot be empty")
        return value


class ProfileUpdate(ProfilePreferences):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    avatar: str | None = Field(default=None, max_length=255)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("Profile name cannot be null")

        value = value.strip()
        if not value:
            raise ValueError("Profile name cannot be empty")

        return value


class ProfileResponse(ProfilePreferences):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    avatar: str | None
    is_owner: bool


class ProfileSelfDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm_name: str = Field(min_length=1, max_length=80)


@router.get("", response_model=list[ProfileResponse])
def list_profiles(db: Session = Depends(get_db)):
    return db.scalars(select(Profile).order_by(Profile.id)).all()


@router.post(
    "",
    response_model=ProfileResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_profile(payload: ProfileCreate, db: Session = Depends(get_db)):
    config = db.get(Installation, 1)
    if config is None or config.owner_id is None:
        raise HTTPException(status_code=409, detail="Complete first-run setup before adding profiles")
    profile = Profile(
        **{**payload.model_dump(), "avatar_seed": payload.avatar_seed or payload.name, "locale": payload.locale or config.locale},
    )

    db.add(profile)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Profile name already exists",
        )

    db.refresh(profile)
    return profile


@router.get("/{profile_id}", response_model=ProfileResponse)
def get_profile(profile_id: int, db: Session = Depends(get_db)):
    profile = db.get(Profile, profile_id)

    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found",
        )

    return profile


@router.patch("/{profile_id}", response_model=ProfileResponse)
def update_profile(
    profile_id: int,
    payload: ProfileUpdate,
    db: Session = Depends(get_db),
):
    profile = db.get(Profile, profile_id)

    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found",
        )

    updates = payload.model_dump(exclude_unset=True)

    for field, value in updates.items():
        setattr(profile, field, value)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Profile name already exists",
        )

    db.refresh(profile)
    return profile


async def remove_profile(profile_id: int, db: Session) -> Response:
    profile = db.get(Profile, profile_id)

    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found",
        )

    if profile.is_owner:
        raise HTTPException(409, "The installation owner cannot be deleted")
    db.delete(profile)
    db.commit()
    from playback.source_sessions import source_sessions
    from watch_together.domain import rooms
    from api.watch_together import broadcast
    source_sessions.revoke_profile(profile_id)
    with rooms.lock:
        for room in rooms.rooms.values():
            for participant in list(room.participants.values()):
                if participant.profile_id == profile_id:
                    rooms.leave(room,participant)
            broadcast(room)

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_profile(profile_id: int, db: Session = Depends(get_db), owner: Profile = Depends(require_owner)):
    return await remove_profile(profile_id, db)


@router.post("/{profile_id}/self-delete", status_code=status.HTTP_204_NO_CONTENT)
async def self_delete_profile(
    profile_id: int,
    payload: ProfileSelfDelete,
    x_profile_id: int = Header(alias="X-Profile-Id"),
    db: Session = Depends(get_db),
):
    if x_profile_id != profile_id:
        raise HTTPException(403, "Selected profile does not match")
    profile = db.get(Profile, profile_id)
    if profile is None:
        raise HTTPException(404, "Profile not found")
    if profile.is_owner:
        raise HTTPException(409, "The installation owner cannot be deleted")
    if payload.confirm_name != profile.name:
        raise HTTPException(400, "Profile name confirmation does not match")
    return await remove_profile(profile_id, db)
