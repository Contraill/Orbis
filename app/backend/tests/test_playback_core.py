import asyncio
import sqlite3
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from db.base import Base
from db.models.playback import PlaybackState
from db.models.profile import Profile
from db.models.provider import ProviderState
from db.session import get_db
from main import app
from playback.matching import (
    match_audio_track,
    match_subtitle_track,
)
from playback.schemas import PlaybackStateUpdate
from playback.service import (
    PlaybackService,
    episode_identity,
    get_playback_state,
    movie_identity,
    upsert_playback_state,
)
from providers.contract import MediaProvider
from providers.manager import ProviderManager
from providers.schemas import (
    AudioTrack,
    PlaybackSource,
    ProviderCapabilities,
    ProviderHealthResult,
    SubtitleTrack,
)


class PlaybackProvider(MediaProvider):
    capabilities = ProviderCapabilities(
        movie=True,
        episode=True,
        protocols=["hls"],
        selectable_audio=True,
        selectable_subtitles=True,
    )

    def __init__(
        self,
        provider_id: str,
        priority: int,
    ) -> None:
        self.id = provider_id
        self.name = provider_id
        self.default_enabled = True
        self.default_priority = priority

    async def health_check(self):
        return ProviderHealthResult(healthy=True)

    async def search(self, query):
        return []

    def _source(self) -> list[PlaybackSource]:
        return [
            PlaybackSource(
                provider_id=self.id,
                url=(
                    "https://example.invalid/"
                    f"{self.id}/master.m3u8"
                ),
                protocol="hls",
                audio_tracks=[
                    AudioTrack(
                        language="en",
                        kind="original",
                    ),
                    AudioTrack(
                        language="tr",
                        kind="dub",
                    ),
                ],
                subtitle_tracks=[
                    SubtitleTrack(
                        language="tr",
                        kind="manifest",
                    )
                ],
            )
        ]

    async def resolve_movie(self, tmdb_id):
        return self._source()

    async def resolve_episode(self, tmdb_id, season, episode):
        return self._source()


class PlaybackTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def foreign_keys(connection, record):
            if isinstance(connection, sqlite3.Connection):
                connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
        )
        self.db = self.sessions()
        self.profile_one = Profile(name="One")
        self.profile_two = Profile(name="Two")
        self.db.add_all([
            self.profile_one,
            self.profile_two,
        ])
        self.db.commit()

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


class PlaybackStateApiTests(PlaybackTestCase):
    def setUp(self):
        super().setUp()

        def override_db():
            with self.sessions() as session:
                yield session

        app.dependency_overrides[get_db] = override_db
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()
        super().tearDown()

    def test_canonical_movie_upsert_lookup_and_profile_isolation(self):
        url = (
            f"/api/playback/profiles/{self.profile_one.id}"
            "/movie/101/state"
        )
        response = self.client.put(
            url,
            json={
                "position_seconds": 2,
                "preferred_audio_language": "TR_tr",
                "preferred_audio_kind": "dub",
                "subtitles_enabled": True,
                "preferred_subtitle_language": "TR",
            },
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["position_seconds"], 0)
        self.assertEqual(
            body["preferred_audio_language"],
            "tr-tr",
        )

        self.assertEqual(
            self.client.get(url).json()["tmdb_id"],
            101,
        )
        other_url = (
            f"/api/playback/profiles/{self.profile_two.id}"
            "/movie/101/state"
        )
        self.assertIsNone(self.client.get(other_url).json())

        with self.sessions() as db:
            state = db.scalar(select(PlaybackState))
            self.assertEqual(state.content_key, "movie:101")

    def test_client_cannot_supply_content_key(self):
        response = self.client.put(
            (
                f"/api/playback/profiles/{self.profile_one.id}"
                "/movie/101/state"
            ),
            json={
                "position_seconds": 20,
                "content_key": "movie:999",
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_movie_and_episode_identity_are_distinct(self):
        movie = movie_identity(202)
        episode = episode_identity(202, 1, 3)
        upsert_playback_state(
            self.db,
            self.profile_one.id,
            movie,
            PlaybackStateUpdate(position_seconds=20),
        )
        upsert_playback_state(
            self.db,
            self.profile_one.id,
            episode,
            PlaybackStateUpdate(position_seconds=40),
        )

        self.assertEqual(
            get_playback_state(
                self.db,
                self.profile_one.id,
                movie,
            ).content_key,
            "movie:202",
        )
        self.assertEqual(
            get_playback_state(
                self.db,
                self.profile_one.id,
                episode,
            ).content_key,
            "tv:202:s1:e3",
        )

    def test_completed_and_near_end_state_resume_from_zero(self):
        completed = self.client.put(
            (
                f"/api/playback/profiles/{self.profile_one.id}"
                "/movie/303/state"
            ),
            json={
                "position_seconds": 120,
                "duration_seconds": 200,
                "completed": True,
            },
        ).json()
        self.assertTrue(completed["completed"])
        self.assertEqual(completed["position_seconds"], 0)
        self.assertEqual(
            completed["resume_position_seconds"],
            0,
        )

        near_end = self.client.put(
            (
                f"/api/playback/profiles/{self.profile_one.id}"
                "/movie/304/state"
            ),
            json={
                "position_seconds": 95,
                "duration_seconds": 100,
            },
        ).json()
        self.assertTrue(near_end["completed"])
        self.assertEqual(near_end["position_seconds"], 0)

        untouched_short = self.client.put(
            (
                f"/api/playback/profiles/{self.profile_one.id}"
                "/movie/305/state"
            ),
            json={
                "position_seconds": 0,
                "duration_seconds": 8,
            },
        ).json()
        self.assertFalse(untouched_short["completed"])

    def test_failover_endpoint_preserves_logical_state(self):
        fallback = PlaybackProvider("fallback", 10)
        failed = PlaybackProvider("failed", 20)
        all_patch, get_patch = self.provider_patches(
            [fallback, failed]
        )
        service = PlaybackService(ProviderManager())

        with (
            all_patch,
            get_patch,
            patch("api.playback.playback_service", service),
        ):
            response = self.client.post(
                (
                    f"/api/playback/profiles/{self.profile_one.id}"
                    "/movie/306/failover"
                ),
                json={
                    "position_seconds": 123,
                    "duration_seconds": 1800,
                    "completed": False,
                    "last_provider_id": "client-value-is-ignored",
                    "preferred_audio_language": "tr",
                    "preferred_audio_kind": "dub",
                    "subtitles_enabled": True,
                    "preferred_subtitle_language": "tr",
                    "failed_provider_id": "failed",
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            body["resolution"]["selected_provider_id"],
            "fallback",
        )
        self.assertEqual(body["state"]["position_seconds"], 123)
        self.assertEqual(
            body["state"]["preferred_audio_kind"],
            "dub",
        )
        self.assertTrue(body["state"]["subtitles_enabled"])
        self.assertEqual(
            body["state"]["last_provider_id"],
            "fallback",
        )

    def test_missing_profile_is_not_created_implicitly(self):
        response = self.client.put(
            "/api/playback/profiles/9999/movie/1/state",
            json={"position_seconds": 20},
        )
        self.assertEqual(response.status_code, 404)


class PreferenceMatchingTests(unittest.TestCase):
    def test_audio_matching_is_deterministic_and_graceful(self):
        tracks = [
            AudioTrack(language="en", kind="original"),
            AudioTrack(language="tr", kind="original"),
            AudioTrack(language="tr-TR", kind="dub"),
        ]

        exact = match_audio_track(tracks, "tr_TR", "dub")
        self.assertEqual(exact.track.kind, "dub")
        self.assertEqual(
            exact.matched_by,
            "language_and_kind",
        )

        missing = match_audio_track(
            tracks,
            "de",
            "commentary",
        )
        self.assertEqual(missing.track, tracks[0])
        self.assertEqual(
            missing.matched_by,
            "provider_default",
        )

    def test_subtitles_keep_burned_in_non_disableable(self):
        tracks = [
            SubtitleTrack(
                language="en",
                kind="burned_in",
            ),
            SubtitleTrack(
                language="tr",
                kind="manifest",
            ),
        ]

        disabled = match_subtitle_track(
            tracks,
            False,
            "tr",
        )
        self.assertTrue(disabled.enabled)
        self.assertFalse(disabled.can_disable)
        self.assertIsNone(disabled.selected_track)
        self.assertEqual(
            disabled.burned_in_track.kind,
            "burned_in",
        )

        enabled = match_subtitle_track(
            tracks,
            True,
            "tr",
        )
        self.assertEqual(
            enabled.selected_track.language,
            "tr",
        )


class PlaybackOrchestrationTests(PlaybackTestCase):
    def test_last_provider_is_preferred_over_normal_priority(self):
        first = PlaybackProvider("first", 10)
        previous = PlaybackProvider("previous", 20)
        all_patch, get_patch = self.provider_patches(
            [first, previous]
        )
        identity = movie_identity(404)
        upsert_playback_state(
            self.db,
            self.profile_one.id,
            identity,
            PlaybackStateUpdate(
                position_seconds=60,
                last_provider_id="previous",
            ),
        )

        with all_patch, get_patch:
            session = asyncio.run(
                PlaybackService(ProviderManager()).resolve(
                    self.db,
                    self.profile_one.id,
                    identity,
                )
            )

        self.assertEqual(
            session.resolution.selected_provider_id,
            "previous",
        )
        self.assertEqual(
            session.state.resume_position_seconds,
            60,
        )

    def test_open_last_provider_falls_back(self):
        fallback = PlaybackProvider("fallback", 10)
        previous = PlaybackProvider("previous", 20)
        manager = ProviderManager()
        all_patch, get_patch = self.provider_patches(
            [fallback, previous]
        )
        identity = movie_identity(505)
        upsert_playback_state(
            self.db,
            self.profile_one.id,
            identity,
            PlaybackStateUpdate(
                position_seconds=70,
                last_provider_id="previous",
            ),
        )

        with all_patch, get_patch:
            manager.sync_registry(self.db)
            state = self.db.get(ProviderState, "previous")
            state.circuit_open_until = (
                datetime.now(timezone.utc)
                + timedelta(minutes=5)
            )
            self.db.commit()

            session = asyncio.run(
                PlaybackService(manager).resolve(
                    self.db,
                    self.profile_one.id,
                    identity,
                )
            )

        self.assertEqual(
            session.resolution.selected_provider_id,
            "fallback",
        )
        self.assertEqual(
            session.resolution.attempts[0].error,
            "Circuit open",
        )

    def test_failover_preserves_position_and_preferences(self):
        fallback = PlaybackProvider("fallback", 10)
        failed = PlaybackProvider("failed", 20)
        manager = ProviderManager()
        all_patch, get_patch = self.provider_patches(
            [fallback, failed]
        )
        identity = episode_identity(606, 2, 4)
        upsert_playback_state(
            self.db,
            self.profile_one.id,
            identity,
            PlaybackStateUpdate(
                position_seconds=123,
                duration_seconds=2400,
                last_provider_id="failed",
                preferred_audio_language="tr",
                preferred_audio_kind="dub",
                subtitles_enabled=True,
                preferred_subtitle_language="tr",
            ),
        )

        with all_patch, get_patch:
            session = asyncio.run(
                PlaybackService(manager).resolve(
                    self.db,
                    self.profile_one.id,
                    identity,
                    excluded_provider_ids={"failed"},
                )
            )

        self.assertEqual(
            session.resolution.selected_provider_id,
            "fallback",
        )
        self.assertEqual(session.state.position_seconds, 123)
        self.assertEqual(
            session.state.preferred_audio_language,
            "tr",
        )
        self.assertEqual(
            session.state.preferred_audio_kind,
            "dub",
        )
        self.assertTrue(session.state.subtitles_enabled)
        self.assertEqual(
            session.state.preferred_subtitle_language,
            "tr",
        )
        self.assertEqual(
            session.state.last_provider_id,
            "fallback",
        )
        self.assertEqual(
            session.selected_audio.track.kind,
            "dub",
        )
