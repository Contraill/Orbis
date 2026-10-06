import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from main import app
from db.base import Base
from db.session import get_db
from db.models.foundation import Installation, LocalizedMetadata, ViewingDay, ViewingProgress
from db.models.profile import Profile, utc_now
from db.models.playback import PlaybackState
from db.models.provider import ProviderState
from activity.service import record_progress
from metadata.schemas import CatalogDetails
from playback.schemas import PlaybackStateUpdate
from playback.service import movie_identity, episode_identity, upsert_playback_state
from core import owner as owner_recovery


class FoundationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{Path(self.temp.name) / 'test.db'}", connect_args={"check_same_thread": False, "timeout": 20})
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        def database():
            with self.sessions() as db:
                yield db
        app.dependency_overrides[get_db] = database
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()
        self.engine.dispose()
        self.temp.cleanup()

    def owner(self):
        result = self.client.post("/api/setup/owner", json={"name": "Owner", "password": "correct-horse-battery"})
        self.assertEqual(result.status_code, 201, result.text)
        self.client.headers["Authorization"] = "Bearer " + result.json()["token"]
        return result.json()["owner_id"]

    def test_fresh_locale_and_atomic_bootstrap(self):
        self.assertEqual(self.client.get("/api/profiles").json(), [])
        self.assertEqual(self.client.get("/api/setup").json()["locale"], "en-US")
        self.assertEqual(self.client.post("/api/profiles", json={"name": "Too early"}).status_code, 409)
        self.client.put("/api/setup/locale", json={"locale": "tr-TR"})
        def claim(n):
            with TestClient(app) as client:
                return client.post("/api/setup/owner", json={"name": f"Owner{n}", "password": "correct-horse-battery"}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(claim, [1, 2]))
        self.assertEqual(sorted(statuses), [201, 409])
        profiles = self.client.get("/api/profiles").json()
        self.assertEqual(len(profiles), 1)
        self.assertTrue(profiles[0]["is_owner"])
        self.assertEqual(profiles[0]["locale"], "tr-TR")
        self.assertEqual(self.client.put("/api/setup/locale", json={"locale": "en-US"}).status_code, 409)

    def test_owner_authority_not_profile_selection_and_lockout(self):
        owner = self.owner()
        viewer = self.client.post("/api/profiles", json={"name": "Viewer"}).json()
        self.assertFalse(viewer["is_owner"])
        self.assertEqual(self.client.patch(f"/api/profiles/{viewer['id']}", json={"is_owner": True}).status_code, 422)
        self.assertEqual(self.client.delete(f"/api/profiles/{owner}").status_code, 409)
        self.client.headers.pop("Authorization")
        for path in ("/api/admin/providers", "/api/admin/provider-editor"):
            self.assertEqual(self.client.get(path, headers={"X-Profile-Id": str(owner)}).status_code, 401)
        self.assertEqual(self.client.post("/api/admin/provider-editor/reference/activate", json={}).status_code, 401)
        self.assertEqual(self.client.delete("/api/admin/provider-editor/reference").status_code, 401)
        other = self.client.post("/api/profiles", json={"name": "Other"})
        self.assertEqual(other.status_code, 201, other.text)
        self.assertFalse(other.json()["is_owner"])
        self.assertEqual(self.client.get("/api/admin/providers").status_code, 401)
        for _ in range(5):
            self.assertEqual(self.client.post("/api/setup/login", json={"password": "wrong"}).status_code, 401)
        self.assertEqual(self.client.post("/api/setup/login", json={"password": "correct-horse-battery"}).status_code, 429)

    def test_profile_preferences_avatar_seeds_and_locale_isolation(self):
        owner = self.owner()
        viewer = self.client.post("/api/profiles", json={"name": "Viewer", "locale": "tr-TR"}).json()
        url = f"/api/profiles/{viewer['id']}"
        renamed = self.client.patch(url, json={"name": "New name", "autoplay_next_episode": False}).json()
        self.assertEqual(renamed["avatar_seed"], "Viewer")
        self.assertFalse(renamed["autoplay_next_episode"])
        self.assertEqual(self.client.get(f"/api/profiles/{owner}").json()["locale"], "en-US")
        seeds = [{"media_type": "movie", "tmdb_id": n} for n in range(1, 7)]
        self.assertEqual(self.client.patch(url, json={"onboarding_seeds": seeds}).status_code, 422)
        self.assertEqual(self.client.patch(url, json={"onboarding_seeds": seeds[:1] * 2}).status_code, 422)
        self.assertEqual(self.client.patch(url, json={"onboarding_seeds": seeds[:5]}).status_code, 200)
        self.assertEqual(self.client.patch(url, json={"locale": None}).status_code, 422)

    def test_viewer_self_delete_requires_matching_selection_and_name(self):
        owner = self.owner()
        viewer = self.client.post("/api/profiles", json={"name": "Viewer to delete"}).json()
        self.client.headers.pop("Authorization")
        url = f"/api/profiles/{viewer['id']}/self-delete"
        confirmed = {"confirm_name": "Viewer to delete"}
        self.assertEqual(self.client.delete(f"/api/profiles/{viewer['id']}").status_code, 401)
        self.assertEqual(self.client.post(url, json=confirmed).status_code, 422)
        self.assertEqual(self.client.post(url, json=confirmed, headers={"X-Profile-Id": str(owner)}).status_code, 403)
        self.assertEqual(self.client.post(url, json={"confirm_name": "Wrong"}, headers={"X-Profile-Id": str(viewer['id'])}).status_code, 400)
        self.assertEqual(self.client.post(f"/api/profiles/{owner}/self-delete", json={"confirm_name": "Owner"}, headers={"X-Profile-Id": str(owner)}).status_code, 409)
        self.assertEqual(self.client.get(url.replace("/self-delete", "")).status_code, 200)
        with self.sessions() as db:
            upsert_playback_state(db, viewer["id"], movie_identity(42), PlaybackStateUpdate(position_seconds=90, duration_seconds=600))
            self.assertIsNotNone(db.scalar(select(PlaybackState).where(PlaybackState.profile_id == viewer["id"])))
        response = self.client.post(url, json=confirmed, headers={"X-Profile-Id": str(viewer['id'])})
        self.assertEqual(response.status_code, 204, response.text)
        self.assertEqual(self.client.get(f"/api/profiles/{viewer['id']}").status_code, 404)
        self.assertEqual([profile["id"] for profile in self.client.get("/api/profiles").json()], [owner])
        with self.sessions() as db:
            self.assertIsNone(db.scalar(select(PlaybackState).where(PlaybackState.profile_id == viewer["id"])))

    def test_avatar_config_is_validated_and_survives_rename(self):
        self.owner()
        viewer = self.client.post("/api/profiles", json={"name": "Avatar viewer"}).json()
        self.assertIsNone(viewer["avatar_config"])
        url = f"/api/profiles/{viewer['id']}"
        config = {"shape": "droplet", "face_preset": "big_eyes", "expression": "wink", "hue": 190, "tone": "mid"}
        response = self.client.patch(url, json={"avatar_config": config, "name": "Renamed avatar viewer"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["avatar_config"], config)
        self.assertEqual(response.json()["avatar_seed"], viewer["avatar_seed"])
        self.assertEqual(self.client.get(url).json()["avatar_config"], config)
        self.assertEqual(self.client.patch(url, json={"avatar_config": {"shape": "unknown"}}).status_code, 422)
        self.assertEqual(self.client.patch(url, json={"avatar_config": {"hue": 999}}).status_code, 422)
        updated = self.client.patch(url, json={"avatar_config": {"shape": "sun", "expression": "sleepy", "hue": 319, "tone": .42}})
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(self.client.get(url).json()["avatar_config"]["hue"], 319)
        self.assertEqual(self.client.patch(url, json={"avatar_config": {"tone": 1.5}}).status_code, 422)

    def test_local_owner_password_recovery_revokes_old_sessions(self):
        self.owner()
        old_token = self.client.headers["Authorization"]
        with patch("core.owner.SessionLocal", self.sessions), patch("core.owner.getpass", side_effect=["new-correct-owner-pass", "new-correct-owner-pass"]):
            owner_recovery.main()
        self.assertEqual(self.client.get("/api/setup/session", headers={"Authorization": old_token}).status_code, 401)
        self.assertEqual(self.client.post("/api/setup/login", json={"password": "correct-horse-battery"}).status_code, 401)
        self.assertEqual(self.client.post("/api/setup/login", json={"password": "new-correct-owner-pass"}).status_code, 200)

    def test_add_profile_accepts_all_onboarding_fields_without_reopening_setup(self):
        owner = self.owner()
        self.client.headers.pop("Authorization")
        values = {
            "name": "Second viewer", "avatar_seed": "independent-seed", "locale": "tr-TR",
            "preferred_audio_language": "en", "preferred_subtitle_language": "tr",
            "subtitles_enabled": True, "autoplay_next_episode": False, "trailer_muted": False,
            "onboarding_seeds": [{"media_type": "tv" if n % 2 else "movie", "tmdb_id": n} for n in range(1, 6)],
        }
        response = self.client.post("/api/profiles", json=values)
        self.assertEqual(response.status_code, 201, response.text)
        created = response.json()
        for key, value in values.items():
            self.assertEqual(created[key], value)
        self.assertFalse(created["is_owner"])
        status = self.client.get("/api/setup").json()
        self.assertFalse(status["setup_required"])
        self.assertEqual(status["owner_id"], owner)
        self.assertEqual(self.client.post("/api/setup/owner", json={"name": "Another owner", "password": "another-owner-password"}).status_code, 409)
        self.assertEqual(self.client.post("/api/profiles", json={**values, "is_owner": True}).status_code, 422)
        self.assertEqual(self.client.get("/api/admin/providers", headers={"X-Profile-Id": str(created["id"])}).status_code, 401)

    def test_owner_can_delete_live_provider_but_not_factory(self):
        from providers import live, registry
        root = Path(self.temp.name) / "providers"
        with patch.object(registry, "LIVE_PROVIDER_ROOT", root), patch.object(live, "LIVE_PROVIDER_ROOT", root):
            registry.reload_registry()
            try:
                self.owner()
                created = self.client.post("/api/admin/provider-editor", json={"provider_id": "delete-test", "name": "Delete test"})
                self.assertEqual(created.status_code, 201, created.text)
                self.assertEqual(self.client.post("/api/admin/provider-editor/delete-test/activate").status_code, 200)
                self.assertIn("delete-test", [p["provider_id"] for p in self.client.get("/api/admin/providers").json()])
                with self.sessions() as db:
                    self.assertIsNotNone(db.get(ProviderState, "delete-test"))
                self.assertEqual(self.client.delete("/api/admin/provider-editor/reference").status_code, 404)
                response = self.client.delete("/api/admin/provider-editor/delete-test")
                self.assertEqual(response.status_code, 204, response.text)
                self.assertFalse((root / "delete-test").exists())
                self.assertNotIn("delete-test", [p["provider_id"] for p in self.client.get("/api/admin/providers").json()])
                with self.sessions() as db:
                    self.assertIsNone(db.get(ProviderState, "delete-test"))
            finally:
                registry.reload_registry()

    def test_localized_metadata_is_not_overwritten(self):
        owner = self.owner()
        en = CatalogDetails(tmdb_id=42, media_type="movie", title="English", original_title="Original", overview="EN", genres=["Drama"])
        tr = en.model_copy(update={"title": "Türkçe", "overview": "TR", "genres": ["Dram"]})
        with patch("metadata.tmdb.TMDBClient.movie_details", new_callable=AsyncMock, side_effect=[en, tr]):
            self.client.get(f"/api/catalog/movie/42?profile_id={owner}")
            self.client.patch(f"/api/profiles/{owner}", json={"locale": "tr-TR"})
            self.client.get(f"/api/catalog/movie/42?profile_id={owner}")
        with self.sessions() as db:
            self.assertEqual(db.get(LocalizedMetadata, ("movie:42", "en-US")).data["title"], "English")
            self.assertEqual(db.get(LocalizedMetadata, ("movie:42", "tr-TR")).data["genres"], ["Dram"])

    def watch(self, profile, identity, start=None, seconds=90, duration=600):
        start = start or utc_now() - timedelta(minutes=10)
        with self.sessions() as db:
            # First real timeupdate establishes the clock; resolution alone does not.
            record_progress(db, profile, identity, PlaybackStateUpdate(position_seconds=.01, duration_seconds=duration), now=start)
            for position in range(0, seconds + 1, 15):
                update = PlaybackStateUpdate(position_seconds=position, duration_seconds=duration, completed=position == duration)
                record_progress(db, profile, identity, update, now=start + timedelta(seconds=position))
                upsert_playback_state(db, profile, identity, update)

    def test_history_suppression_reentry_and_list_independence(self):
        owner = self.owner()
        root = f"/api/library/profiles/{owner}"
        identity = movie_identity(42)
        self.watch(owner, identity)
        self.assertEqual(len(self.client.get(root + "/continue").json()), 1)
        self.assertEqual(self.client.get(root + "/my-list").json(), [])
        self.client.post(root + "/continue/hide", json={"media_type": "movie", "tmdb_id": 42})
        self.assertEqual(self.client.get(root + "/continue").json(), [])
        self.assertEqual(len(self.client.get(root + "/history").json()), 1)
        self.watch(owner, identity, start=utc_now(), seconds=90)
        self.assertEqual(len(self.client.get(root + "/continue").json()), 1)
        self.client.put(root + "/my-list", json={"media_type": "tv", "tmdb_id": 12, "enabled": True})
        self.assertEqual(len(self.client.get(root + "/my-list?kind=tv").json()), 1)
        self.assertEqual(self.client.get(root + "/my-list?kind=movie").json(), [])
        self.client.put(root + "/my-list", json={"media_type": "tv", "tmdb_id": 12, "enabled": False})
        self.assertEqual(len(self.client.get(root + "/history").json()), 1)

    def test_existing_resume_survives_first_short_activity_sample(self):
        owner = self.owner()
        root = f"/api/library/profiles/{owner}"
        identity = movie_identity(42)
        with self.sessions() as db:
            upsert_playback_state(db, owner, identity, PlaybackStateUpdate(position_seconds=120, duration_seconds=600))
        self.assertEqual(len(self.client.get(root + "/continue").json()), 1)
        with self.sessions() as db:
            record_progress(db, owner, identity, PlaybackStateUpdate(position_seconds=120, duration_seconds=600))
            db.commit()
        self.assertEqual(len(self.client.get(root + "/continue").json()), 1)
        self.assertFalse(self.client.get(root + "/signals").json()[0]["meaningful_viewing"])

    def test_series_dedupe_next_episode_and_sustained_progression(self):
        owner = self.owner()
        root = f"/api/library/profiles/{owner}"
        self.watch(owner, episode_identity(10, 1, 1), start=utc_now() - timedelta(days=7), seconds=120, duration=120)
        self.watch(owner, episode_identity(10, 1, 2), seconds=120, duration=120)
        with self.sessions() as db:
            db.add(LocalizedMetadata(content_key="tv:10:season:1", locale="en-US", data={"season_number": 1, "episodes": [{"episode_number": 3, "air_date": "2020-01-01"}]}))
            db.commit()
        cards = self.client.get(root + "/continue?kind=tv").json()
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["episode_number"], 3)
        self.assertEqual(cards[0]["action"], "next_episode")
        signal = self.client.get(root + "/signals").json()[0]
        self.assertTrue(signal["sustained_series_progression"])
        self.assertEqual(signal["completions"], 2)
        self.assertFalse(signal["my_list"])

    def test_seek_tiny_start_and_rewatch(self):
        owner = self.owner()
        root = f"/api/library/profiles/{owner}"
        self.watch(owner, movie_identity(42), seconds=15)
        signals = self.client.get(root + "/signals").json()
        self.assertFalse(signals[0]["meaningful_viewing"])
        with self.sessions() as db:
            p = db.get(ViewingProgress, (owner, "movie:42"))
            record_progress(db, owner, movie_identity(42), PlaybackStateUpdate(position_seconds=600, duration_seconds=600, completed=True), now=p.sampled_at + timedelta(seconds=1))
            db.commit()
            self.assertEqual(p.completions, 0)
        self.watch(owner, movie_identity(55), seconds=120, duration=120)
        self.client.post(root + "/restart", json={"media_type": "movie", "tmdb_id": 55})
        self.watch(owner, movie_identity(55), start=utc_now() + timedelta(seconds=1), seconds=90, duration=120)
        history = self.client.get(root + "/history").json()
        replay = next(h for h in history if h["tmdb_id"] == 55)
        self.assertEqual(replay["completions"], 1)
        self.assertEqual(replay["rewatches"], 1)
        self.client.put(root + "/not-interested", json={"media_type": "movie", "tmdb_id": 55, "enabled": True})
        self.assertTrue(next(s for s in self.client.get(root + "/signals").json() if s["tmdb_id"] == 55)["not_interested"])

    def test_api_recording_isolated_and_idle_saves_do_not_create_history(self):
        owner = self.owner()
        viewer = self.client.post("/api/profiles", json={"name": "Other"}).json()["id"]
        path = f"/api/playback/profiles/{owner}/movie/42/state"
        self.assertEqual(self.client.put(path, json={"position_seconds": 0}).status_code, 200)
        self.assertEqual(self.client.get(f"/api/library/profiles/{owner}/history").json(), [])
        now = utc_now()
        for position in (1, 16, 31, 46, 61, 76):
            with patch("activity.service.utc_now", return_value=now + timedelta(seconds=position)):
                self.assertEqual(self.client.put(path, json={"position_seconds": position, "duration_seconds": 600}).status_code, 200)
        self.assertEqual(len(self.client.get(f"/api/library/profiles/{owner}/history").json()), 1)
        for resource in ("history", "continue", "my-list", "signals"):
            self.assertEqual(self.client.get(f"/api/library/profiles/{viewer}/{resource}").json(), [])
        with self.sessions() as db:
            self.assertEqual(len(db.scalars(select(ViewingDay)).all()), 1)
            # Deleting mutable resume state does not delete durable evidence.
            db.delete(db.scalar(select(PlaybackState)))
            db.commit()
            self.assertEqual(len(db.scalars(select(ViewingProgress)).all()), 1)

    def test_logout_and_expiry_revoke_authority(self):
        from db.models.foundation import AdminSession
        self.owner()
        self.assertEqual(self.client.get("/api/setup/session").status_code, 200)
        self.assertEqual(self.client.post("/api/setup/logout").status_code, 200)
        self.assertEqual(self.client.get("/api/setup/session").status_code, 401)

        result = self.client.post("/api/setup/login", json={"password": "correct-horse-battery"})
        self.client.headers["Authorization"] = "Bearer " + result.json()["token"]
        with self.sessions() as db:
            session = db.scalar(select(AdminSession))
            self.assertNotIn(result.json()["token"], session.token_hash)
            session.expires_at = utc_now() - timedelta(seconds=1)
            db.commit()
        self.assertEqual(self.client.get("/api/setup/session").status_code, 401)

    def test_password_validation_does_not_echo_secrets(self):
        response = self.client.post("/api/setup/owner", json={"name": "Owner", "password": "short-secret"[:11]})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn("short-secre", response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_player_replay_first_sample_after_zero_starts_new_cycle(self):
        owner = self.owner()
        identity = movie_identity(80)
        self.watch(owner, identity, seconds=120, duration=120)
        with self.sessions() as db:
            p = db.get(ViewingProgress, (owner, identity.content_key))
            now = p.sampled_at + timedelta(minutes=1)
            for position in (15, 30, 45):
                record_progress(db, owner, identity, PlaybackStateUpdate(position_seconds=position, duration_seconds=120), now=now + timedelta(seconds=position))
                db.flush()
            self.assertFalse(p.cycle_completed)
            self.assertEqual(p.rewatches, 0)
            for position in (60, 75, 90, 105, 120):
                record_progress(db, owner, identity, PlaybackStateUpdate(position_seconds=position, duration_seconds=120, completed=position == 120), now=now + timedelta(seconds=position))
                db.flush()
            self.assertEqual(p.rewatches, 1)
            self.assertEqual(p.completions, 2)

    def test_stale_start_and_onboarding_are_distinct_from_affinity(self):
        owner = self.owner()
        self.watch(owner, movie_identity(42), start=utc_now() - timedelta(days=40), seconds=15)
        self.client.patch(f"/api/profiles/{owner}", json={"onboarding_seeds": [{"media_type": "tv", "tmdb_id": 7}]})
        result = {s["tmdb_id"]: s for s in self.client.get(f"/api/library/profiles/{owner}/signals").json()}
        self.assertTrue(result[42]["stale_started"])
        self.assertFalse(result[42]["meaningful_viewing"])
        self.assertTrue(result[7]["onboarding"])
        self.assertEqual(result[7]["watched_seconds"], 0)
        self.assertFalse(result[7]["my_list"])
