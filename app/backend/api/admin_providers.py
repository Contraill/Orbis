import asyncio
from time import perf_counter
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from core.errors import safe_text
from core.auth import require_owner
from db.models.profile import Profile

from db.models.provider import ProviderEvent
from db.session import get_db
from playback.schemas import PlaybackResolutionSummary
from playback.choices import manifest_qualities
from playback.hls import read_manifest
from playback.upstream import UpstreamRejected, new_http_client, open_upstream
from providers.source_policy import quality_score, rank_sources, source_expiry_status
from providers.manager import (
    ProviderNotRegistered,
    ResolutionFailed,
    provider_manager,
)
from providers.registry import discovery_errors, get_provider
from providers.schemas import (
    PlaybackResolution,
    ProviderAdminView,
    ProviderEventView,
    ProviderHealthCheckReport,
)


router = APIRouter(
    prefix="/api/admin/providers",
    tags=["admin-providers"],
)


class ProviderUpdate(BaseModel):
    enabled: bool | None = None
    priority: int | None = Field(
        default=None,
        ge=0,
        le=10000,
    )


class AdminSourceDiagnostic(BaseModel):
    provider_id: str
    source_id: str | None
    source_label: str | None
    status: Literal["reachable", "failed"]
    latency_ms: float | None
    quality_classes: list[str]
    audio_languages: list[str]
    audio_kinds: list[str]
    subtitle_languages: list[str]
    burned_in_subtitles: bool
    reason: str | None
    ranking_reasons: list[str]


class AdminResolveResult(PlaybackResolutionSummary):
    sources: list[AdminSourceDiagnostic]


def provider_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Provider not registered",
    )


def resolution_failed(exc: ResolutionFailed) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail={
            "message": str(exc),
            "attempts": [
                attempt.model_dump(mode="json")
                for attempt in exc.attempts
            ],
        },
    )


def resolution_summary(
    resolution: PlaybackResolution,
) -> PlaybackResolutionSummary:
    return PlaybackResolutionSummary(
        selected_provider_id=resolution.selected_provider_id,
        attempts=resolution.attempts,
    )


async def diagnostic_result(resolution: PlaybackResolution, profile: Profile) -> AdminResolveResult:
    ranked = rank_sources(
        resolution.sources,
        preferred_audio_language=profile.preferred_audio_language,
        subtitles_enabled=profile.subtitles_enabled,
        preferred_subtitle_language=profile.preferred_subtitle_language,
    )

    async def inspect(source):
        started = perf_counter()
        quality = quality_score(source.quality)
        qualities = [f"{quality}p"] if quality else []
        try:
            async with asyncio.timeout(8), new_http_client() as client:
                response, _ = await open_upstream(client, source, source.url)
                reachable = response.status_code in {200, 206}
                if reachable and source.protocol == "hls" and response.status_code == 200:
                    discovered = manifest_qualities(await read_manifest(response))
                    if discovered:
                        qualities = [item.label for item in discovered]
                await response.aclose()
        except (httpx.HTTPError, OSError, UpstreamRejected, TimeoutError):
            reachable = False
        audio_languages = sorted({track.language for track in source.audio_tracks if track.language})
        subtitle_languages = sorted({track.language for track in source.subtitle_tracks if track.language})
        reasons = []
        if reachable and source is ranked[0]:
            reasons.append("Preferred by current profile")
        if reachable and source_expiry_status(source) == "healthy":
            reasons.append("Healthy")
        if profile.preferred_audio_language in audio_languages:
            reasons.append(f"{profile.preferred_audio_language} audio")
        if profile.subtitles_enabled and profile.preferred_subtitle_language in subtitle_languages:
            reasons.append(f"{profile.preferred_subtitle_language} subtitles")
        if not profile.subtitles_enabled and any(track.kind == "burned_in" for track in source.subtitle_tracks):
            reasons.append("Unavoidable burned-in subtitles")
        if qualities:
            reasons.append(qualities[0])
        return AdminSourceDiagnostic(
            provider_id=source.provider_id,
            source_id=source.source_id,
            source_label=source.source_label,
            status="reachable" if reachable else "failed",
            latency_ms=round((perf_counter() - started) * 1000, 1),
            quality_classes=qualities,
            audio_languages=audio_languages,
            audio_kinds=sorted({track.kind for track in source.audio_tracks}),
            subtitle_languages=subtitle_languages,
            burned_in_subtitles=any(track.kind == "burned_in" for track in source.subtitle_tracks),
            reason=None if reachable else "Source could not be reached",
            ranking_reasons=reasons,
        )

    return AdminResolveResult(
        **resolution_summary(resolution).model_dump(),
        sources=await asyncio.gather(*(inspect(source) for source in ranked)),
    )


@router.get(
    "/discovery-errors",
    response_model=dict[str, str],
)
def provider_discovery_errors():
    return discovery_errors()


@router.get("", response_model=list[ProviderAdminView])
def list_providers(
    db: Session = Depends(get_db),
):
    return provider_manager.list_providers(db)


@router.patch(
    "/{provider_id}",
    response_model=ProviderAdminView,
)
def update_provider(
    provider_id: str,
    payload: ProviderUpdate,
    db: Session = Depends(get_db),
):
    if get_provider(provider_id) is None:
        raise provider_not_found()

    try:
        return provider_manager.update_provider(
            db,
            provider_id,
            enabled=payload.enabled,
            priority=payload.priority,
        )
    except ProviderNotRegistered:
        raise provider_not_found()


@router.post(
    "/{provider_id}/test",
    response_model=ProviderHealthCheckReport,
)
async def test_provider(
    provider_id: str,
    db: Session = Depends(get_db),
):
    if get_provider(provider_id) is None:
        raise provider_not_found()

    try:
        return await provider_manager.health_check(
            db,
            provider_id,
        )
    except ProviderNotRegistered:
        raise provider_not_found()


@router.get(
    "/{provider_id}/logs",
    response_model=list[ProviderEventView],
)
def provider_logs(
    provider_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    if get_provider(provider_id) is None:
        raise provider_not_found()

    rows = db.scalars(
        select(ProviderEvent)
        .where(ProviderEvent.provider_id == provider_id)
        .order_by(ProviderEvent.id.desc())
        .limit(limit)
    ).all()
    return [ProviderEventView.model_validate(row).model_copy(update={"message":safe_text(row.message)}) for row in rows]


@router.post(
    "/resolve-test/movie/{tmdb_id}",
    response_model=AdminResolveResult,
)
async def fallback_movie_test(
    tmdb_id: int = Path(gt=0),
    db: Session = Depends(get_db),
    profile: Profile = Depends(require_owner),
):
    try:
        return await diagnostic_result(
            await provider_manager.resolve_movie(
                db,
                tmdb_id,
            ), profile,
        )
    except ResolutionFailed as exc:
        raise resolution_failed(exc)


@router.post(
    "/resolve-test/tv/{tmdb_id}/season/{season}/episode/{episode}",
    response_model=AdminResolveResult,
)
async def fallback_episode_test(
    tmdb_id: int = Path(gt=0),
    season: int = Path(ge=0),
    episode: int = Path(gt=0),
    db: Session = Depends(get_db),
    profile: Profile = Depends(require_owner),
):
    try:
        return await diagnostic_result(
            await provider_manager.resolve_episode(
                db,
                tmdb_id,
                season,
                episode,
            ), profile,
        )
    except ResolutionFailed as exc:
        raise resolution_failed(exc)


@router.post(
    "/{provider_id}/resolve-test/movie/{tmdb_id}",
    response_model=AdminResolveResult,
)
async def provider_movie_test(
    provider_id: str,
    tmdb_id: int = Path(gt=0),
    db: Session = Depends(get_db),
    profile: Profile = Depends(require_owner),
):
    if get_provider(provider_id) is None:
        raise provider_not_found()

    try:
        return await diagnostic_result(
            await provider_manager.resolve_movie(
                db,
                tmdb_id,
                provider_id=provider_id,
                force=True,
            ), profile,
        )
    except ProviderNotRegistered:
        raise provider_not_found()
    except ResolutionFailed as exc:
        raise resolution_failed(exc)


@router.post(
    "/{provider_id}/resolve-test/tv/{tmdb_id}/season/{season}/episode/{episode}",
    response_model=AdminResolveResult,
)
async def provider_episode_test(
    provider_id: str,
    tmdb_id: int = Path(gt=0),
    season: int = Path(ge=0),
    episode: int = Path(gt=0),
    db: Session = Depends(get_db),
    profile: Profile = Depends(require_owner),
):
    if get_provider(provider_id) is None:
        raise provider_not_found()

    try:
        return await diagnostic_result(
            await provider_manager.resolve_episode(
                db,
                tmdb_id,
                season,
                episode,
                provider_id=provider_id,
                force=True,
            ), profile,
        )
    except ProviderNotRegistered:
        raise provider_not_found()
    except ResolutionFailed as exc:
        raise resolution_failed(exc)
