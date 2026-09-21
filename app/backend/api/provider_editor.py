from typing import Any

from fastapi import (
    APIRouter,
    HTTPException,
    status,
)
from pydantic import BaseModel, Field

from providers.live import (
    LiveProviderError,
    LiveProviderValidationError,
    activate_draft,
    create_live_provider,
    get_settings,
    list_live_providers,
    provider_editor_state,
    rollback_provider,
    save_draft,
    save_settings,
    validate_draft,
)
from providers.registry import (
    discovery_errors,
    reload_registry,
)


router = APIRouter(
    prefix="/api/admin/provider-editor",
    tags=["provider-editor"],
)


class ProviderCreate(BaseModel):
    provider_id: str = Field(
        min_length=2,
        max_length=64,
    )
    name: str = Field(
        min_length=1,
        max_length=100,
    )


class ProviderCodeUpdate(BaseModel):
    code: str = Field(
        max_length=500_000,
    )


class ProviderSettingsUpdate(BaseModel):
    settings: dict[str, Any]


def handle_error(exc: LiveProviderError):
    if isinstance(
        exc,
        LiveProviderValidationError,
    ):
        raise HTTPException(
            status_code=422,
            detail={
                "message": str(exc),
                "errors": exc.errors,
            },
        ) from exc

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=str(exc),
    ) from exc


@router.get("")
def live_providers():
    return list_live_providers()


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
)
def create_provider(payload: ProviderCreate):
    try:
        return create_live_provider(
            payload.provider_id,
            payload.name,
        )
    except LiveProviderError as exc:
        handle_error(exc)


@router.get("/discovery-errors")
def live_discovery_errors():
    return discovery_errors()


@router.post("/reload")
def reload_live_registry():
    providers = reload_registry()

    return {
        "providers": sorted(providers),
        "errors": discovery_errors(),
    }


@router.get("/{provider_id}")
def provider_editor(provider_id: str):
    try:
        return provider_editor_state(
            provider_id
        )
    except LiveProviderError as exc:
        handle_error(exc)


@router.put("/{provider_id}/draft")
def update_draft(
    provider_id: str,
    payload: ProviderCodeUpdate,
):
    try:
        return save_draft(
            provider_id,
            payload.code,
        )
    except LiveProviderError as exc:
        handle_error(exc)


@router.post("/{provider_id}/validate")
def validate_provider(provider_id: str):
    try:
        return validate_draft(
            provider_id
        )
    except LiveProviderError as exc:
        handle_error(exc)


@router.post("/{provider_id}/activate")
def activate_provider(provider_id: str):
    try:
        return activate_draft(
            provider_id
        )
    except LiveProviderError as exc:
        handle_error(exc)


@router.post(
    "/{provider_id}/rollback/{version}"
)
def rollback(
    provider_id: str,
    version: str,
):
    try:
        return rollback_provider(
            provider_id,
            version,
        )
    except LiveProviderError as exc:
        handle_error(exc)


@router.get("/{provider_id}/settings")
def provider_settings(provider_id: str):
    try:
        return get_settings(
            provider_id
        )
    except LiveProviderError as exc:
        handle_error(exc)


@router.put("/{provider_id}/settings")
def update_settings(
    provider_id: str,
    payload: ProviderSettingsUpdate,
):
    try:
        return save_settings(
            provider_id,
            payload.settings,
        )
    except LiveProviderError as exc:
        handle_error(exc)
