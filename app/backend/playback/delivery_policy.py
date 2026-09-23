"""Delivery decisions contain no provider or player-specific rules."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import Lock
from typing import Literal
from urllib.parse import urlsplit

from providers.schemas import PlaybackSource
from providers.source_policy import utc_now


ResourceKind = Literal["root", "manifest", "segment", "init", "key", "subtitle"]
ALL_RESOURCES = frozenset({"root", "manifest", "segment", "init", "key", "subtitle"})
COMPATIBILITY_TTL = timedelta(minutes=15)


@dataclass(frozen=True)
class DeliveryPlan:
    relay: frozenset[str] = frozenset()

    @property
    def mode(self) -> str:
        if not self.relay:
            return "direct"
        return "full" if ALL_RESOURCES <= self.relay else "selective"

    def include(self, *kinds: str) -> "DeliveryPlan":
        # Rewriting the root is necessary to make a child relay addressable.
        return DeliveryPlan(self.relay | {"root", *kinds})


class DeliveryPolicy:
    def __init__(self):
        self._observations: dict[tuple, tuple[datetime, DeliveryPlan]] = {}
        self._lock = Lock()

    def clear(self):
        with self._lock:
            self._observations.clear()

    def _key(self, source: PlaybackSource, audience: str):
        # No host-wide inference: observations belong to this client and source path.
        parsed = urlsplit(source.url)
        return audience, source.provider_id, parsed.netloc, parsed.path

    def choose(self, source: PlaybackSource, audience: str = "", *, now=None):
        if source.headers or source.delivery.resource_headers or source.delivery.egress == "resolution":
            return DeliveryPlan(ALL_RESOURCES)
        now = now or utc_now()
        with self._lock:
            self._observations = {
                key: value for key, value in self._observations.items()
                if value[0] > now
            }
            entry = self._observations.get(self._key(source, audience)) if audience else None
        return entry[1] if entry else DeliveryPlan()

    def observe(self, source, audience, plan, *, now=None):
        if not audience:
            return
        now = now or utc_now()
        with self._lock:
            if len(self._observations) >= 1024:
                oldest = min(self._observations, key=lambda k: self._observations[k][0])
                del self._observations[oldest]
            key = self._key(source, audience)
            previous = self._observations.get(key)
            # Escalation does not extend the original TTL indefinitely.
            until = previous[0] if previous and previous[0] > now else now + COMPATIBILITY_TTL
            self._observations[key] = (until, plan)


delivery_policy = DeliveryPolicy()
