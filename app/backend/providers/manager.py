import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from time import perf_counter

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.config import get_settings
from db.models.provider import ProviderEvent, ProviderState
from providers.contract import MediaProvider, ProviderError
from providers.registry import all_providers, get_provider
from providers.schemas import (
    PlaybackResolution,
    PlaybackSource,
    ProviderAdminView,
    ProviderAttempt,
    ProviderHealthCheckReport,
)
from providers.source_policy import usable_sources


CIRCUIT_FAILURE_THRESHOLD = 5
CIRCUIT_OPEN_MINUTES = 10


class ProviderNotRegistered(ProviderError):
    pass


class ResolutionFailed(ProviderError):
    def __init__(self, attempts: list[ProviderAttempt]):
        super().__init__("No provider could resolve this media")
        self.attempts = attempts


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def provider_error_message(exc: Exception) -> str:
    if isinstance(exc, TimeoutError):
        return "Provider operation timed out"
    return str(exc) or type(exc).__name__


def circuit_is_open(state: ProviderState) -> bool:
    if state.circuit_open_until is None:
        return False

    now = utc_now()

    if state.circuit_open_until.tzinfo is None:
        now = now.replace(tzinfo=None)

    return state.circuit_open_until > now


class ProviderManager:
    def sync_registry(self, db: Session) -> None:
        providers = all_providers()

        existing = {
            state.provider_id
            for state in db.scalars(
                select(ProviderState)
            ).all()
        }

        changed = False

        for provider in providers.values():
            if provider.id in existing:
                continue

            db.add(
                ProviderState(
                    provider_id=provider.id,
                    enabled=provider.default_enabled,
                    priority=provider.default_priority,
                )
            )
            changed = True

        if changed:
            try:
                db.commit()
            except IntegrityError:
                # Another request may have synchronized first.
                db.rollback()

    def _state(
        self,
        db: Session,
        provider_id: str,
    ) -> ProviderState:
        self.sync_registry(db)

        provider = get_provider(provider_id)
        if provider is None:
            raise ProviderNotRegistered(provider_id)

        state = db.get(ProviderState, provider_id)
        if state is None:
            raise ProviderNotRegistered(provider_id)

        return state

    def _view(
        self,
        state: ProviderState,
    ) -> ProviderAdminView:
        provider = get_provider(state.provider_id)

        if provider is None:
            raise ProviderNotRegistered(state.provider_id)

        if not state.enabled:
            provider_status = "disabled"
        elif circuit_is_open(state):
            provider_status = "circuit_open"
        elif state.failure_count > 0:
            provider_status = "degraded"
        elif state.last_success_at is not None:
            provider_status = "healthy"
        else:
            provider_status = "unknown"

        return ProviderAdminView(
            provider_id=provider.id,
            name=provider.name,
            enabled=state.enabled,
            priority=state.priority,
            status=provider_status,
            capabilities=provider.capabilities,
            failure_count=state.failure_count,
            circuit_open_until=state.circuit_open_until,
            last_success_at=state.last_success_at,
            last_failure_at=state.last_failure_at,
            last_health_check_at=state.last_health_check_at,
            last_latency_ms=state.last_latency_ms,
            last_error=state.last_error,
        )

    def list_providers(
        self,
        db: Session,
    ) -> list[ProviderAdminView]:
        self.sync_registry(db)

        states = db.scalars(
            select(ProviderState).order_by(
                ProviderState.priority,
                ProviderState.provider_id,
            )
        ).all()

        return [
            self._view(state)
            for state in states
            if get_provider(state.provider_id) is not None
        ]

    def update_provider(
        self,
        db: Session,
        provider_id: str,
        *,
        enabled: bool | None = None,
        priority: int | None = None,
    ) -> ProviderAdminView:
        state = self._state(db, provider_id)

        if enabled is not None:
            state.enabled = enabled

        if priority is not None:
            state.priority = priority

        db.commit()
        db.refresh(state)

        return self._view(state)

    def _event(
        self,
        db: Session,
        provider_id: str,
        level: str,
        event: str,
        message: str | None = None,
    ) -> None:
        db.add(
            ProviderEvent(
                provider_id=provider_id,
                level=level,
                event=event,
                message=message,
            )
        )

    def _success(
        self,
        db: Session,
        state: ProviderState,
        latency_ms: float,
        event: str,
        message: str | None = None,
    ) -> None:
        state.failure_count = 0
        state.circuit_open_until = None
        state.last_success_at = utc_now()
        state.last_latency_ms = latency_ms
        state.last_error = None

        self._event(
            db,
            state.provider_id,
            "info",
            event,
            message,
        )

        db.commit()

    def _failure(
        self,
        db: Session,
        state: ProviderState,
        latency_ms: float,
        event: str,
        error: str,
    ) -> None:
        state.failure_count += 1
        state.last_failure_at = utc_now()
        state.last_latency_ms = latency_ms
        state.last_error = error

        if state.failure_count >= CIRCUIT_FAILURE_THRESHOLD:
            state.circuit_open_until = (
                utc_now()
                + timedelta(minutes=CIRCUIT_OPEN_MINUTES)
            )

        self._event(
            db,
            state.provider_id,
            "error",
            event,
            error,
        )

        db.commit()

    async def health_check(
        self,
        db: Session,
        provider_id: str,
    ) -> ProviderHealthCheckReport:
        state = self._state(db, provider_id)
        provider = get_provider(provider_id)

        if provider is None:
            raise ProviderNotRegistered(provider_id)

        started = perf_counter()

        try:
            result = await asyncio.wait_for(
                provider.health_check(),
                timeout=get_settings().provider_operation_timeout_seconds,
            )
            latency_ms = (perf_counter() - started) * 1000
            state.last_health_check_at = utc_now()

            if result.healthy:
                self._success(
                    db,
                    state,
                    latency_ms,
                    "health_ok",
                    result.message,
                )
            else:
                self._failure(
                    db,
                    state,
                    latency_ms,
                    "health_failed",
                    result.message or "Health check failed",
                )

        except Exception as exc:
            latency_ms = (perf_counter() - started) * 1000
            state.last_health_check_at = utc_now()

            self._failure(
                db,
                state,
                latency_ms,
                "health_failed",
                provider_error_message(exc),
            )

            result_message = provider_error_message(exc)
            healthy = False
        else:
            result_message = result.message
            healthy = result.healthy

        db.refresh(state)

        return ProviderHealthCheckReport(
            provider=self._view(state),
            healthy=healthy,
            message=result_message,
            latency_ms=latency_ms,
        )

    async def _resolve(
        self,
        db: Session,
        resolver: Callable[
            [MediaProvider],
            Awaitable[list[PlaybackSource]],
        ],
        *,
        capability: str,
        provider_id: str | None = None,
        preferred_provider_id: str | None = None,
        excluded_provider_ids: set[str] | None = None,
        require_healthy_source: bool = False,
        force: bool = False,
    ) -> PlaybackResolution:
        self.sync_registry(db)

        if provider_id is not None:
            states = [self._state(db, provider_id)]
        else:
            states = db.scalars(
                select(ProviderState)
                .where(ProviderState.enabled.is_(True))
                .order_by(
                    ProviderState.priority,
                    ProviderState.provider_id,
                )
            ).all()

            if preferred_provider_id is not None:
                states.sort(
                    key=lambda state: (
                        state.provider_id
                        != preferred_provider_id,
                        state.priority,
                        state.provider_id,
                    )
                )

        excluded = excluded_provider_ids or set()

        attempts: list[ProviderAttempt] = []

        for state in states:
            if state.provider_id in excluded:
                attempts.append(
                    ProviderAttempt(
                        provider_id=state.provider_id,
                        status="skipped",
                        error="Excluded after playback failure",
                    )
                )
                continue

            provider = get_provider(state.provider_id)

            if provider is None:
                continue

            if not getattr(provider.capabilities, capability):
                attempts.append(
                    ProviderAttempt(
                        provider_id=state.provider_id,
                        status="skipped",
                        error=f"{capability.title()} is not supported",
                    )
                )
                continue

            if not force and not state.enabled:
                attempts.append(
                    ProviderAttempt(
                        provider_id=state.provider_id,
                        status="skipped",
                        error="Provider disabled",
                    )
                )
                continue

            if not force and circuit_is_open(state):
                attempts.append(
                    ProviderAttempt(
                        provider_id=state.provider_id,
                        status="skipped",
                        error="Circuit open",
                    )
                )
                continue

            started = perf_counter()

            try:
                sources = await asyncio.wait_for(
                    resolver(provider),
                    timeout=get_settings().provider_operation_timeout_seconds,
                )

                if not sources:
                    raise ProviderError(
                        "Provider returned no playable sources"
                    )

                for source in sources:
                    if source.provider_id != provider.id:
                        raise ProviderError(
                            "Provider returned a source with "
                            "an invalid provider_id"
                        )

                sources = usable_sources(
                    sources,
                    require_healthy=require_healthy_source,
                )
                if not sources:
                    raise ProviderError(
                        "Provider returned no compatible unexpired sources"
                    )

            except Exception as exc:
                latency_ms = (perf_counter() - started) * 1000

                self._failure(
                    db,
                    state,
                    latency_ms,
                    "resolve_failed",
                    provider_error_message(exc),
                )

                attempts.append(
                    ProviderAttempt(
                        provider_id=provider.id,
                        status="failed",
                        latency_ms=latency_ms,
                        error=provider_error_message(exc),
                    )
                )

                continue

            latency_ms = (perf_counter() - started) * 1000

            self._success(
                db,
                state,
                latency_ms,
                "resolve_ok",
            )

            attempts.append(
                ProviderAttempt(
                    provider_id=provider.id,
                    status="success",
                    latency_ms=latency_ms,
                )
            )

            return PlaybackResolution(
                selected_provider_id=provider.id,
                sources=sources,
                attempts=attempts,
            )

        raise ResolutionFailed(attempts)

    async def resolve_movie(
        self,
        db: Session,
        tmdb_id: int,
        *,
        provider_id: str | None = None,
        preferred_provider_id: str | None = None,
        excluded_provider_ids: set[str] | None = None,
        require_healthy_source: bool = False,
        force: bool = False,
    ) -> PlaybackResolution:
        return await self._resolve(
            db,
            lambda provider: provider.resolve_movie(tmdb_id),
            capability="movie",
            provider_id=provider_id,
            preferred_provider_id=preferred_provider_id,
            excluded_provider_ids=excluded_provider_ids,
            require_healthy_source=require_healthy_source,
            force=force,
        )

    async def resolve_episode(
        self,
        db: Session,
        tmdb_id: int,
        season: int,
        episode: int,
        *,
        provider_id: str | None = None,
        preferred_provider_id: str | None = None,
        excluded_provider_ids: set[str] | None = None,
        require_healthy_source: bool = False,
        force: bool = False,
    ) -> PlaybackResolution:
        return await self._resolve(
            db,
            lambda provider: provider.resolve_episode(
                tmdb_id,
                season,
                episode,
            ),
            capability="episode",
            provider_id=provider_id,
            preferred_provider_id=preferred_provider_id,
            excluded_provider_ids=excluded_provider_ids,
            require_healthy_source=require_healthy_source,
            force=force,
        )


provider_manager = ProviderManager()
