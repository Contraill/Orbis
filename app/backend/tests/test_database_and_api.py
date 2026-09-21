import sqlite3
import unittest
from datetime import timezone
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from db.base import Base
from db.models.playback import PlaybackState
from db.models.profile import Profile
from db.models.provider import ProviderState
from db.session import get_db
from main import app
from metadata.schemas import CatalogPage


class DatabaseAndApiTests(unittest.TestCase):
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

        def override_db():
            with self.sessions() as session:
                yield session

        app.dependency_overrides[get_db] = override_db
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()
        self.engine.dispose()

    def create_profile(self, name="Viewer"):
        response = self.client.post(
            "/api/profiles",
            json={"name": name},
        )
        self.assertEqual(response.status_code, 201)
        return response.json()

    def test_profile_crud_edges_and_playback_cascade(self):
        profile = self.create_profile("  Viewer  ")
        self.assertEqual(profile["name"], "Viewer")

        duplicate = self.client.post(
            "/api/profiles",
            json={"name": "Viewer"},
        )
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(
            self.client.post(
                "/api/profiles",
                json={"name": "   "},
            ).status_code,
            422,
        )
        self.assertEqual(
            self.client.patch(
                f"/api/profiles/{profile['id']}",
                json={"name": None},
            ).status_code,
            422,
        )
        self.assertEqual(
            self.client.get("/api/profiles/9999").status_code,
            404,
        )

        with self.sessions() as db:
            db.add(
                PlaybackState(
                    profile_id=profile["id"],
                    media_type="movie",
                    tmdb_id=100,
                )
            )
            db.commit()

        response = self.client.delete(
            f"/api/profiles/{profile['id']}"
        )
        self.assertEqual(response.status_code, 204)
        with self.sessions() as db:
            self.assertEqual(
                len(db.scalars(select(PlaybackState)).all()),
                0,
            )

    def test_foreign_keys_and_canonical_content_uniqueness(self):
        one = self.create_profile("One")
        two = self.create_profile("Two")

        with self.sessions() as db:
            db.add(
                PlaybackState(
                    profile_id=9999,
                    media_type="movie",
                    tmdb_id=1,
                )
            )
            with self.assertRaises(IntegrityError):
                db.commit()
            db.rollback()

            first = PlaybackState(
                profile_id=one["id"],
                content_key="caller-value-is-not-identity",
                media_type="movie",
                tmdb_id=200,
            )
            other_profile = PlaybackState(
                profile_id=two["id"],
                media_type="movie",
                tmdb_id=200,
            )
            db.add_all([first, other_profile])
            db.commit()
            self.assertEqual(first.content_key, "movie:200")

            db.add(
                PlaybackState(
                    profile_id=one["id"],
                    content_key="different-key",
                    media_type="movie",
                    tmdb_id=200,
                )
            )
            with self.assertRaises(IntegrityError):
                db.commit()
            db.rollback()

            db.add(
                PlaybackState(
                    profile_id=one["id"],
                    media_type="tv",
                    tmdb_id=300,
                    season_number=None,
                    episode_number=1,
                )
            )
            with self.assertRaises(ValueError):
                db.commit()
            db.rollback()

    def test_sqlite_datetime_round_trip_is_aware_utc(self):
        with self.sessions() as db:
            state = ProviderState(provider_id="clock")
            db.add(state)
            db.commit()
            db.expire_all()
            loaded = db.get(ProviderState, "clock")
            self.assertEqual(loaded.created_at.tzinfo, timezone.utc)

    def test_catalog_route_uses_mocked_tmdb(self):
        page = CatalogPage(page=1, total_pages=0, results=[])
        with patch(
            "api.catalog.tmdb.search",
            new=AsyncMock(return_value=page),
        ) as mocked:
            response = self.client.get(
                "/api/catalog/search",
                params={"query": "matrix"},
            )

        self.assertEqual(response.status_code, 200)
        mocked.assert_awaited_once_with("matrix", 1)
