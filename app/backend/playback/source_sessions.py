from dataclasses import dataclass, field
from datetime import datetime, timedelta
from secrets import token_urlsafe
from threading import Lock

from playback.delivery_policy import DeliveryPlan, ResourceKind
from playback.upstream import UpstreamRejected, origin

from providers.schemas import PlaybackSource
from providers.source_policy import (
    aware_utc,
    source_expiry_status,
    source_validation_error,
    utc_now,
)


SESSION_TTL = timedelta(hours=6)
EXPIRED_SOURCE_REFRESH_GRACE = timedelta(minutes=10)
MAX_SOURCE_SESSIONS = 256
MAX_SESSION_RESOURCES = 4096
MAX_TOTAL_RESOURCES = 32768


class SourceSessionNotFound(LookupError):
    pass


class SourceSessionScopeError(PermissionError):
    pass


class SourceSessionExpired(LookupError):
    pass


@dataclass(frozen=True)
class SourceResource:
    resource_id: str
    url: str
    kind: ResourceKind
    parent_id: str | None = None
    depth: int = 0


@dataclass(frozen=True)
class SourceSession:
    session_id: str
    profile_id: int
    content_key: str
    source: PlaybackSource
    created_at: datetime
    retained_until: datetime
    plan: DeliveryPlan = field(default_factory=DeliveryPlan)
    audience: str = ""
    resources: dict[str, SourceResource] = field(default_factory=dict)
    resource_index: dict[tuple[str, str], str] = field(default_factory=dict)
    recovery_attempts: set[str] = field(default_factory=set)
    evidence: list[dict] = field(default_factory=list)


class SourceSessionRegistry:
    def __init__(self) -> None:
        self._sessions: dict[str, SourceSession] = {}
        self._lock = Lock()

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()

    def issue(
        self,
        profile_id: int,
        content_key: str,
        source: PlaybackSource,
        *,
        now: datetime | None = None,
        plan: DeliveryPlan | None = None,
        audience: str = "",
    ) -> SourceSession:
        validation_error = source_validation_error(source, now=now)
        if validation_error is not None:
            raise ValueError(validation_error)

        current = aware_utc(now or utc_now())
        retained_until = current + SESSION_TTL
        if source.expires_at is not None:
            retained_until = min(
                retained_until,
                aware_utc(source.expires_at)
                + EXPIRED_SOURCE_REFRESH_GRACE,
            )

        session = SourceSession(
            session_id=token_urlsafe(32),
            profile_id=profile_id,
            content_key=content_key,
            source=source.model_copy(deep=True),
            created_at=current,
            retained_until=retained_until,
            plan=plan or DeliveryPlan(),
            audience=audience,
            resources={"root": SourceResource("root", source.url, "root")},
            resource_index={(source.url, "root"): "root"},
        )

        with self._lock:
            self._purge_locked(current)
            if len(self._sessions) >= MAX_SOURCE_SESSIONS:
                oldest = min(
                    self._sessions.values(),
                    key=lambda existing: existing.created_at,
                )
                del self._sessions[oldest.session_id]
            self._sessions[session.session_id] = session
        return session

    def register(self, session, parent, url, kind):
        allowed = {origin(session.source.url), *(origin(item) for item in session.source.delivery.resource_origins)}
        if origin(url) not in allowed:
            raise UpstreamRejected("Manifest resource origin is not allowed")
        if parent.depth >= 8:
            raise UpstreamRejected("Manifest ancestry is too deep")
        with self._lock:
            if parent.resource_id not in session.resources:
                raise UpstreamRejected("Unknown manifest ancestor")
            key = (url, kind)
            existing = session.resource_index.get(key)
            if existing:
                return session.resources[existing]
            if (
                len(session.resources) >= MAX_SESSION_RESOURCES
                or sum(len(item.resources) for item in self._sessions.values()) >= MAX_TOTAL_RESOURCES
            ):
                raise UpstreamRejected("Resource registry capacity reached")
            resource = SourceResource(token_urlsafe(18), url, kind, parent.resource_id, parent.depth + 1)
            session.resources[resource.resource_id] = resource
            session.resource_index[key] = resource.resource_id
            return resource

    def resources(self, session):
        with self._lock:
            return list(session.resources.values())

    def claim_recovery(self, session, kind):
        with self._lock:
            if kind in session.recovery_attempts:
                return False
            session.recovery_attempts.add(kind)
            return True

    def diagnostics(self):
        with self._lock:
            self._purge_locked(utc_now())
            return [{
                "session": session.session_id[:8],
                "provider_id": session.source.provider_id,
                "content_key": session.content_key,
                "mode": session.plan.mode,
                "relayed_resource_types": sorted(session.plan.relay),
                "registered_resources": len(session.resources),
                "retained_until": session.retained_until,
                "evidence": list(session.evidence),
            } for session in list(self._sessions.values())[-64:]]

    def get(
        self,
        session_id: str,
        *,
        profile_id: int | None = None,
        content_key: str | None = None,
        for_proxy: bool = False,
        now: datetime | None = None,
    ) -> SourceSession:
        current = aware_utc(now or utc_now())
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise SourceSessionNotFound(session_id)
            if session.retained_until <= current:
                del self._sessions[session_id]
                raise SourceSessionNotFound(session_id)

        if profile_id is not None and session.profile_id != profile_id:
            raise SourceSessionScopeError(session_id)
        if (
            content_key is not None
            and session.content_key != content_key
        ):
            raise SourceSessionScopeError(session_id)
        if (
            for_proxy
            and source_expiry_status(session.source, now=current)
            == "expired"
        ):
            raise SourceSessionExpired(session_id)
        return session

    def _purge_locked(self, now: datetime) -> None:
        expired = [
            session_id
            for session_id, session in self._sessions.items()
            if session.retained_until <= now
        ]
        for session_id in expired:
            del self._sessions[session_id]


source_sessions = SourceSessionRegistry()
