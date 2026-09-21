import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from db.base import Base
import db.models  # noqa: F401
from db.models.provider import ProviderState
from providers.contract import MediaProvider, ProviderUnavailable
from providers.manager import (
    CIRCUIT_FAILURE_THRESHOLD,
    ProviderManager,
)
from providers.schemas import (
    PlaybackSource,
    ProviderCapabilities,
    ProviderHealthResult,
)


class StubProvider(MediaProvider):
    capabilities = ProviderCapabilities(
        movie=True,
        episode=True,
        protocols=["hls"],
    )

    def __init__(
        self,
        provider_id: str,
        priority: int,
        *,
        fails: bool = False,
        delay: float = 0,
        movie: bool = True,
    ) -> None:
        self.id = provider_id
        self.name = provider_id
        self.default_priority = priority
        self.default_enabled = True
        self.fails = fails
        self.delay = delay
        self.capabilities = self.capabilities.model_copy(
            update={"movie": movie}
        )

    async def health_check(self):
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fails:
            raise ProviderUnavailable("unavailable")
        return ProviderHealthResult(healthy=True)

    async def search(self, query):
        return []

    async def resolve_movie(self, tmdb_id):
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fails:
            raise ProviderUnavailable("unavailable")
        return [
            PlaybackSource(
                provider_id=self.id,
                url=f"https://example.invalid/{tmdb_id}",
                protocol="hls",
            )
        ]

    async def resolve_episode(self, tmdb_id, season, episode):
        return await self.resolve_movie(tmdb_id)


class ProviderManagerTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.manager = ProviderManager()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def provider_patches(self, providers):
        mapping = {provider.id: provider for provider in providers}
        return (
            patch(
                "providers.manager.all_providers",
                return_value=mapping,
            ),
            patch(
                "providers.manager.get_provider",
                side_effect=mapping.get,
            ),
        )

    def test_fallback_records_failure_then_selects_next(self):
        broken = StubProvider("broken", 10, fails=True)
        healthy = StubProvider("healthy", 20)
        all_patch, get_patch = self.provider_patches(
            [broken, healthy]
        )

        with all_patch, get_patch:
            result = asyncio.run(
                self.manager.resolve_movie(self.db, 42)
            )

        self.assertEqual(result.selected_provider_id, "healthy")
        self.assertEqual(
            [attempt.status for attempt in result.attempts],
            ["failed", "success"],
        )
        state = self.db.get(ProviderState, "broken")
        self.assertEqual(state.failure_count, 1)
        self.assertEqual(state.last_error, "unavailable")

    def test_open_circuit_is_skipped_by_fallback(self):
        broken = StubProvider("broken", 10, fails=True)
        healthy = StubProvider("healthy", 20)
        all_patch, get_patch = self.provider_patches(
            [broken, healthy]
        )

        with all_patch, get_patch:
            for _ in range(CIRCUIT_FAILURE_THRESHOLD):
                with self.assertRaises(Exception):
                    asyncio.run(
                        self.manager.resolve_movie(
                            self.db,
                            42,
                            provider_id="broken",
                            force=True,
                        )
                    )

            result = asyncio.run(
                self.manager.resolve_movie(self.db, 42)
            )

        self.assertEqual(result.selected_provider_id, "healthy")
        self.assertEqual(result.attempts[0].status, "skipped")
        self.assertEqual(result.attempts[0].error, "Circuit open")
        state = self.db.get(ProviderState, "broken")
        self.assertIsNotNone(state.circuit_open_until)

    def test_expired_circuit_retries_and_success_resets_it(self):
        provider = StubProvider("recovering", 10, fails=True)
        all_patch, get_patch = self.provider_patches([provider])

        with all_patch, get_patch:
            for _ in range(CIRCUIT_FAILURE_THRESHOLD):
                with self.assertRaises(Exception):
                    asyncio.run(
                        self.manager.resolve_movie(
                            self.db,
                            42,
                            provider_id="recovering",
                            force=True,
                        )
                    )

            state = self.db.get(ProviderState, "recovering")
            state.circuit_open_until = (
                datetime.now(timezone.utc)
                - timedelta(seconds=1)
            )
            self.db.commit()
            provider.fails = False

            result = asyncio.run(
                self.manager.resolve_movie(self.db, 42)
            )

        self.assertEqual(result.selected_provider_id, "recovering")
        self.db.refresh(state)
        self.assertEqual(state.failure_count, 0)
        self.assertIsNone(state.circuit_open_until)

    def test_timeout_falls_back_and_counts_failure(self):
        slow = StubProvider("slow", 10, delay=0.1)
        healthy = StubProvider("healthy", 20)
        all_patch, get_patch = self.provider_patches(
            [slow, healthy]
        )
        settings = SimpleNamespace(
            provider_operation_timeout_seconds=0.001
        )

        with all_patch, get_patch, patch(
            "providers.manager.get_settings",
            return_value=settings,
        ):
            result = asyncio.run(
                self.manager.resolve_movie(self.db, 42)
            )

        self.assertEqual(result.selected_provider_id, "healthy")
        self.assertEqual(
            result.attempts[0].error,
            "Provider operation timed out",
        )

    def test_unsupported_capability_is_skipped(self):
        unsupported = StubProvider(
            "unsupported",
            10,
            movie=False,
        )
        healthy = StubProvider("healthy", 20)
        all_patch, get_patch = self.provider_patches(
            [unsupported, healthy]
        )

        with all_patch, get_patch:
            result = asyncio.run(
                self.manager.resolve_movie(self.db, 42)
            )

        self.assertEqual(result.selected_provider_id, "healthy")
        self.assertEqual(result.attempts[0].status, "skipped")
        state = self.db.get(ProviderState, "unsupported")
        self.assertEqual(state.failure_count, 0)
