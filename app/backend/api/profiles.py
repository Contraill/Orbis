from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db.models.profile import Profile
from db.session import get_db


router = APIRouter(prefix="/api/profiles", tags=["profiles"])


class ProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    avatar: str | None = Field(default=None, max_length=255)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Profile name cannot be empty")
        return value


class ProfileUpdate(BaseModel):
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


class ProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    avatar: str | None


@router.get("", response_model=list[ProfileResponse])
def list_profiles(db: Session = Depends(get_db)):
    return db.scalars(select(Profile).order_by(Profile.id)).all()


@router.post(
    "",
    response_model=ProfileResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_profile(payload: ProfileCreate, db: Session = Depends(get_db)):
    profile = Profile(
        name=payload.name,
        avatar=payload.avatar,
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


@router.delete(
    "/{profile_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_profile(profile_id: int, db: Session = Depends(get_db)):
    profile = db.get(Profile, profile_id)

    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found",
        )

    db.delete(profile)
    db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)
