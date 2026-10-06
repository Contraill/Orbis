import asyncio
import sqlite3
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from db.base import Base
from db.models.profile import Profile
from db.session import get_db
from main import app
from playback.matching import (
    match_audio_track,
    match_subtitle_track,
)
from playback.schemas import PlaybackStateUpdate
from playback.service import (
    PlaybackService,
    movie_identity,
    upsert_playback_state,
)
from playback.source_sessions import source_sessions
from providers.contract import MediaProvider
from providers.manager import ProviderManager
from providers.schemas import (
    AudioTrack,
    PlaybackSource,
    ProviderCapabilities,
    ProviderHealthResult,
    SubtitleTrack,
)
from providers.source_policy import (
    rank_sources,
    source_expiry_status,
)


def source(
    provider_id: str,
    name: str,
    *,
    protocol: str = "hls",
    quality: str | None = None,
    expires_at: datetime | None = None,
    headers: dict[str, str] | None = None,
) -> PlaybackSource:
    suffix = "mp4" if protocol == "http" else "m3u8"
    return PlaybackSource(
        provider_id=provider_id,
        url=f"https://media.example/{name}.{suffix}",
        protocol=protocol,
        quality=quality,
        expires_at=expires_at,
        headers=headers or {},
        audio_tracks=[
            AudioTrack(
                language="tr",
                kind="dub",
                track_id="audio-tr-dub",
            )
        ],
        subtitle_tracks=[
            SubtitleTrack(
                language="tr",
                kind="manifest",
                track_id="subtitle-tr",
            )
        ],
    )


class SequencedProvider(MediaProvider):
    capabilities = ProviderCapabilities(
        movie=True,
        episode=True,
        protocols=["hls", "dash", "http"],
        selectable_audio=True,
        selectable_subtitles=True,
    )

    def __init__(
        self,
        provider_id: str,
        priority: int,
        batches: list[list[PlaybackSource]],
    ) -> None:
        self.id = provider_id
        self.name = provider_id
        self.default_enabled = True
        self.default_priority = priority
        self.batches = batches
        self.calls = 0

    async def health_check(self):
        return ProviderHealthResult(healthy=True)

    async def search(self, query):
        return []

    def next_sources(self):
        index = min(self.calls, len(self.batches) - 1)
        self.calls += 1
        return self.batches[index]

    async def resolve_movie(self, tmdb_id):
        return self.next_sources()

    async def resolve_episode(self, tmdb_id, season, episode):
        return self.next_sources()


class HardeningTestCase(unittest.TestCase):
    def setUp(self):
        discovery = patch("playback.choices.discover_qualities", return_value=[])
        discovery.start()
        self.addCleanup(discovery.stop)
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
        self.profile = Profile(name="Playback")
        self.db.add(self.profile)
        self.db.commit()
        source_sessions.clear()

        def override_db():
            with self.sessions() as session:
                yield session

        app.dependency_overrides[get_db] = override_db
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()
        source_sessions.clear()
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


class SourceRankingTests(unittest.TestCase):
    def test_same_content_resolves_locally_for_different_profile_preferences(self):
        turkish = source("provider", "turkish", quality="1080p")
        turkish.source_id = "turkish"
        original = source("provider", "original", quality="1080p")
        original.source_id = "original"
        original.audio_tracks = [AudioTrack(language="en", kind="original", track_id="audio-en")]
        original.subtitle_tracks = [SubtitleTrack(language="tr", kind="manifest", track_id="subtitle-tr")]
        sources = [turkish, original]
        can = rank_sources(sources, preferred_audio_language="tr", subtitles_enabled=False)
        zey = rank_sources(sources, preferred_audio_language="en", preferred_audio_kind="original",
                           preferred_subtitle_language="tr", subtitles_enabled=True)
        self.assertEqual(can[0].source_id, "turkish")
        self.assertEqual(zey[0].source_id, "original")

    def test_profile_audio_subtitles_health_and_fallback_rank_sources(self):
        now = datetime(2030, 1, 1, tzinfo=timezone.utc)
        preferred = source("provider", "preferred", quality="1080p", expires_at=now + timedelta(hours=1))
        no_audio = source("provider", "no-audio", quality="1080p", expires_at=now + timedelta(hours=1))
        no_audio.audio_tracks = []
        no_subtitles = source("provider", "no-subtitles", quality="1080p", expires_at=now + timedelta(hours=1))
        no_subtitles.subtitle_tracks = []
        near = source("provider", "near", quality="1080p", expires_at=now + timedelta(seconds=30))
        preferences = dict(preferred_audio_language="tr", preferred_audio_kind="dub", preferred_subtitle_language="tr", subtitles_enabled=True, now=now)
        self.assertEqual(rank_sources([no_audio, preferred], **preferences)[0], preferred)
        self.assertEqual(rank_sources([no_subtitles, preferred], **preferences)[0], preferred)
        self.assertEqual(rank_sources([near, preferred], **preferences)[0], preferred)
        self.assertEqual(len(rank_sources([no_audio, no_subtitles], **preferences)), 2)
        without_subtitles = rank_sources([no_subtitles, preferred], preferred_subtitle_language="tr", subtitles_enabled=False, now=now)
        self.assertEqual(without_subtitles[0], no_subtitles)
        burned = source("provider", "burned", quality="1080p", expires_at=now + timedelta(hours=1))
        burned.subtitle_tracks = [SubtitleTrack(language="tr", kind="burned_in", track_id="burned")]
        self.assertEqual(rank_sources([burned, preferred], subtitles_enabled=False, now=now)[0], preferred)

    def test_ranking_is_deterministic_and_rejects_expired(self):
        now = datetime(2030, 1, 1, tzinfo=timezone.utc)
        expired = source(
            "provider",
            "expired",
            quality="8K",
            expires_at=now - timedelta(seconds=1),
        )
        near = source(
            "provider",
            "near",
            quality="4K UHD",
            expires_at=now + timedelta(seconds=30),
        )
        healthy = source(
            "provider",
            "healthy",
            protocol="dash",
            quality="Full HD",
            expires_at=now + timedelta(hours=1),
        )
        unknown = source(
            "provider",
            "unknown",
            quality="premium",
        )

        first = rank_sources(
            [near, expired, unknown, healthy],
            now=now,
        )
        second = rank_sources(
            [healthy, unknown, expired, near],
            now=now,
        )

        self.assertEqual(first, second)
        self.assertEqual(first[0].url, healthy.url)
        self.assertNotIn(expired, first)
        self.assertEqual(
            source_expiry_status(near, now=now),
            "near_expiry",
        )

        higher_without_audio = source(
            "provider",
            "higher-without-audio",
            quality="4K",
        )
        higher_without_audio.audio_tracks = []
        preferred_audio = source(
            "provider",
            "preferred-audio",
            quality="1080p",
        )
        with_preference = rank_sources(
            [higher_without_audio, preferred_audio],
            preferred_audio_language="tr",
            preferred_audio_kind="dub",
            now=now,
        )
        self.assertEqual(
            with_preference[0].url,
            preferred_audio.url,
        )

    def test_stable_track_ids_precede_language_and_fallback(self):
        audio = [
            AudioTrack(
                language="tr",
                kind="original",
                track_id="original",
            ),
            AudioTrack(
                language="en",
                kind="dub",
                track_id="stable-dub",
            ),
        ]
        by_id = match_audio_track(
            audio,
            "tr",
            "original",
            "stable-dub",
        )
        fallback = match_audio_track(
            audio,
            "tr",
            "original",
            "missing",
        )
        self.assertEqual(by_id.track.track_id, "stable-dub")
        self.assertEqual(by_id.matched_by, "track_id")
        self.assertEqual(fallback.track.track_id, "original")

        subtitles = [
            SubtitleTrack(
                language="tr",
                kind="manifest",
                track_id="tr-track",
            ),
            SubtitleTrack(
                language="en",
                kind="external",
                track_id="stable-en",
            ),
        ]
        selected = match_subtitle_track(
            subtitles,
            True,
            "tr",
            "stable-en",
        )
        missing = match_subtitle_track(
            subtitles,
            True,
            "tr",
            "missing",
        )
        self.assertEqual(
            selected.selected_track.track_id,
            "stable-en",
        )
        self.assertEqual(
            missing.selected_track.track_id,
            "tr-track",
        )


class CrossProviderPreferenceTests(HardeningTestCase):
    def test_later_provider_matching_profile_beats_playable_fallback(self):
        fallback_source = source("fallback", "fallback", quality="1080p")
        fallback_source.audio_tracks = [AudioTrack(language="en", kind="original")]
        fallback_source.subtitle_tracks = []
        matching_source = source("matching", "matching", quality="1080p")
        providers = [SequencedProvider("fallback", 10, [[fallback_source]]),
                     SequencedProvider("matching", 20, [[matching_source]])]
        all_patch, get_patch = self.provider_patches(providers)
        preferences = dict(preferred_audio_language="tr", preferred_audio_kind="dub",
                           preferred_subtitle_language="tr", subtitles_enabled=True)
        with all_patch, get_patch:
            matching = asyncio.run(ProviderManager().resolve_movie(
                self.db, 42, source_preferences=preferences))
        self.assertEqual(matching.selected_provider_id, "matching")
        self.assertEqual([attempt.status for attempt in matching.attempts], ["success", "success"])

    def test_unavailable_language_keeps_first_playable_provider(self):
        first = source("first", "first")
        first.audio_tracks = [AudioTrack(language="en", kind="original")]
        second = source("second", "second")
        second.audio_tracks = [AudioTrack(language="fr", kind="dub")]
        providers = [SequencedProvider("first", 10, [[first]]), SequencedProvider("second", 20, [[second]])]
        all_patch, get_patch = self.provider_patches(providers)
        with all_patch, get_patch:
            result = asyncio.run(ProviderManager().resolve_movie(
                self.db, 42, source_preferences={"preferred_audio_language": "tr"}))
        self.assertEqual(result.selected_provider_id, "first")


class RefreshOrchestrationTests(HardeningTestCase):
    def _initial_state(self, provider_id: str):
        upsert_playback_state(
            self.db,
            self.profile.id,
            movie_identity(700),
            PlaybackStateUpdate(
                position_seconds=125,
                duration_seconds=1800,
                last_provider_id=provider_id,
                preferred_audio_language="tr",
                preferred_audio_kind="dub",
                subtitles_enabled=True,
                preferred_subtitle_language="tr",
            ),
        )

    def test_near_expiry_refresh_prefers_current_provider(self):
        now = datetime.now(timezone.utc)
        preferred = SequencedProvider(
            "preferred",
            20,
            [
                [source(
                    "preferred",
                    "near",
                    expires_at=now + timedelta(seconds=60),
                )],
                [source(
                    "preferred",
                    "refreshed",
                    expires_at=now + timedelta(hours=1),
                )],
            ],
        )
        fallback = SequencedProvider(
            "fallback",
            10,
            [[source("fallback", "fallback")]],
        )
        self._initial_state("preferred")
        manager = ProviderManager()
        service = PlaybackService(manager)
        all_patch, get_patch = self.provider_patches(
            [fallback, preferred]
        )

        with all_patch, get_patch:
            initial = asyncio.run(service.resolve(
                self.db,
                self.profile.id,
                movie_identity(700),
            ))
            self.assertEqual(
                initial.source_expiry_status,
                "near_expiry",
            )
            self.assertLessEqual(
                initial.refresh_at,
                datetime.now(timezone.utc),
            )

            payload = {
                "position_seconds": 321,
                "duration_seconds": 1800,
                "completed": False,
                "last_provider_id": "ignored",
                "preferred_audio_language": "tr",
                "preferred_audio_kind": "dub",
                "preferred_audio_track_id": "audio-tr-dub",
                "subtitles_enabled": True,
                "preferred_subtitle_language": "tr",
                "preferred_subtitle_track_id": "subtitle-tr",
                "source_session_id": initial.source_session_id,
            }
            with patch("api.playback.playback_service", service):
                response = self.client.post(
                    (
                        f"/api/playback/profiles/{self.profile.id}"
                        "/movie/700/refresh"
                    ),
                    json=payload,
                )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            body["resolution"]["selected_provider_id"],
            "preferred",
        )
        self.assertEqual(body["state"]["position_seconds"], 321)
        self.assertEqual(
            body["state"]["preferred_audio_kind"],
            "dub",
        )
        self.assertTrue(body["state"]["subtitles_enabled"])
        self.assertEqual(
            body["selected_audio"]["track"]["track_id"],
            "audio-tr-dub",
        )

    def test_refresh_falls_back_when_preferred_stays_near_expiry(self):
        now = datetime.now(timezone.utc)
        preferred = SequencedProvider(
            "preferred",
            20,
            [[source(
                "preferred",
                "near",
                expires_at=now + timedelta(seconds=60),
            )]],
        )
        fallback = SequencedProvider(
            "fallback",
            10,
            [[source(
                "fallback",
                "healthy",
                expires_at=now + timedelta(hours=1),
            )]],
        )
        self._initial_state("preferred")
        manager = ProviderManager()
        service = PlaybackService(manager)
        all_patch, get_patch = self.provider_patches(
            [fallback, preferred]
        )

        with all_patch, get_patch:
            initial = asyncio.run(service.resolve(
                self.db,
                self.profile.id,
                movie_identity(700),
            ))
            with patch("api.playback.playback_service", service):
                response = self.client.post(
                    (
                        f"/api/playback/profiles/{self.profile.id}"
                        "/movie/700/refresh"
                    ),
                    json={
                        "position_seconds": 400,
                        "duration_seconds": 1800,
                        "preferred_audio_language": "tr",
                        "preferred_audio_kind": "dub",
                        "subtitles_enabled": True,
                        "preferred_subtitle_language": "tr",
                        "source_session_id": (
                            initial.source_session_id
                        ),
                    },
                )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            body["resolution"]["selected_provider_id"],
            "fallback",
        )
        self.assertEqual(body["state"]["position_seconds"], 400)
        self.assertEqual(
            body["resolution"]["attempts"][0]["provider_id"],
            "preferred",
        )


class PlaybackProxyTests(HardeningTestCase):
    def test_proxy_rejects_unknown_tokens_and_client_urls(self):
        unknown = self.client.get(
            "/api/playback/sources/not-a-real-session"
        )
        arbitrary = self.client.post(
            "/api/playback/sources",
            json={"url": "http://127.0.0.1/private"},
        )
        query = self.client.get(
            "/api/playback/sources/not-a-real-session"
            "?url=http://127.0.0.1/private"
        )

        self.assertEqual(unknown.status_code, 404)
        self.assertIn(arbitrary.status_code, {404, 405})
        self.assertEqual(query.status_code, 404)

    def test_range_passthrough_and_provider_header_secrecy(self):
        entry = source_sessions.issue(
            self.profile.id,
            "movie:900",
            source(
                "secure",
                "video",
                protocol="http",
                headers={
                    "Authorization": "Bearer provider-secret",
                    "Host": "forbidden.example",
                },
            ),
        )
        captured: dict[str, str] = {}

        class Body(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b"data"

        def upstream(request: httpx.Request):
            captured.update(dict(request.headers))
            return httpx.Response(
                206,
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Length": "4",
                    "Content-Range": "bytes 0-3/100",
                    "Accept-Ranges": "bytes",
                    "X-Upstream-Secret": "hidden",
                },
                stream=Body(),
            )

        client = httpx.AsyncClient(
            transport=httpx.MockTransport(upstream)
        )
        with (
            patch("api.playback_proxy._new_http_client", return_value=client),
            patch("playback.upstream.public_address", return_value="93.184.216.34"),
        ):
            response = self.client.get(
                f"/api/playback/sources/{entry.session_id}",
                headers={
                    "Range": "bytes=0-3",
                    "Authorization": "Bearer client-secret",
                },
            )

        self.assertEqual(response.status_code, 206)
        self.assertEqual(
            captured.get("host"),
            "media.example",
        )
        self.assertEqual(response.content, b"data")
        self.assertEqual(captured["range"], "bytes=0-3")
        self.assertEqual(
            captured["authorization"],
            "Bearer provider-secret",
        )
        self.assertNotEqual(
            captured["authorization"],
            "Bearer client-secret",
        )
        self.assertNotIn("x-upstream-secret", response.headers)
        self.assertEqual(
            response.headers["content-range"],
            "bytes 0-3/100",
        )

    def test_session_response_hides_url_and_headers(self):
        provider = SequencedProvider(
            "secure",
            10,
            [[source(
                "secure",
                "private-origin",
                protocol="http",
                headers={"Authorization": "Bearer top-secret"},
            )]],
        )
        all_patch, get_patch = self.provider_patches([provider])
        service = PlaybackService(ProviderManager())

        with (
            all_patch,
            get_patch,
            patch(
                "api.admin_providers.get_provider",
                return_value=provider,
            ),
        ):
            session = asyncio.run(service.resolve(
                self.db,
                self.profile.id,
                movie_identity(901),
            ))
            self.assertEqual(self.client.post("/api/admin/providers/secure/resolve-test/movie/901").status_code, 401)
            from core.auth import issue_session
            from db.models.foundation import Installation
            self.profile.is_owner = True
            self.db.add(Installation(id=1, locale="en-US", owner_id=self.profile.id))
            token = issue_session(self.db, self.profile.id)
            self.db.commit()
            self.client.headers["Authorization"] = "Bearer " + token
            admin_response = self.client.post(
                "/api/admin/providers/secure/resolve-test/movie/901"
            )

        response = session.model_dump(mode="json")
        serialized = session.model_dump_json()
        self.assertTrue(
            response["selected_source"]["url"].startswith(
                "/api/playback/sources/"
            )
        )
        self.assertNotIn("headers", response["selected_source"])
        self.assertNotIn("top-secret", serialized)
        self.assertNotIn("private-origin", serialized)
        self.assertEqual(admin_response.status_code, 200)
        self.assertNotIn("sources", admin_response.json())
        self.assertNotIn("top-secret", admin_response.text)
