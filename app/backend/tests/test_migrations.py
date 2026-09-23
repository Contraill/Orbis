import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]


class MigrationTests(unittest.TestCase):
    def test_fresh_upgrade_has_expected_head_and_tables(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "fresh.db"
            env = os.environ.copy()
            env["DATABASE_URL"] = f"sqlite:///{database}"

            subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                cwd=BACKEND_ROOT,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )

            with closing(
                sqlite3.connect(database)
            ) as connection:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master "
                        "WHERE type = 'table'"
                    )
                }
                revision = connection.execute(
                    "SELECT version_num FROM alembic_version"
                ).fetchone()[0]

            self.assertTrue(
                {
                    "profiles",
                    "provider_states",
                    "provider_events",
                    "playback_states",
                    "client_sessions",
                    "content_markers",
                }.issubset(tables)
            )
            self.assertEqual(revision, "e64a0c31f952")
            with closing(sqlite3.connect(database)) as connection, connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM profiles").fetchone()[0], 0)
                self.assertIsNone(connection.execute("SELECT owner_id FROM installation").fetchone()[0])
            subprocess.run([sys.executable, "-m", "alembic", "check"], cwd=BACKEND_ROOT, env=env, check=True, capture_output=True, text=True)

    def test_existing_install_keeps_profiles_and_playback_and_locks_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "legacy.db"
            env = {**os.environ, "DATABASE_URL": f"sqlite:///{database}"}
            def migrate(target):
                subprocess.run([sys.executable, "-m", "alembic", "upgrade", target], cwd=BACKEND_ROOT, env=env, check=True, capture_output=True, text=True)
            migrate("a37d2e901b44")
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.execute("INSERT INTO profiles (id,name,created_at,updated_at) VALUES (4,'Existing','2026-01-01','2026-01-01'),(9,'Second','2026-01-01','2026-01-01')")
                connection.execute("INSERT INTO playback_states (profile_id,content_key,media_type,tmdb_id,position_seconds,completed,subtitles_enabled,updated_at) VALUES (4,'movie:42','movie',42,123,0,0,'2026-01-01')")
            migrate("head")
            with closing(sqlite3.connect(database)) as connection, connection:
                self.assertEqual(connection.execute("SELECT id,is_owner,avatar_seed FROM profiles ORDER BY id").fetchall(), [(4,1,"Existing"),(9,0,"Second")])
                self.assertEqual(connection.execute("SELECT owner_id,password_hash FROM installation").fetchone(), (4,None))
                self.assertEqual(connection.execute("SELECT position_seconds FROM playback_states").fetchone()[0], 123)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM viewing_progress").fetchone()[0], 0)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM client_sessions").fetchone()[0], 0)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM content_markers").fetchone()[0], 0)

    def test_catalog_upgrade_backfills_both_locales_without_changing_source(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "catalog.db"
            env = {**os.environ, "DATABASE_URL": f"sqlite:///{database}"}
            def migrate(target):
                subprocess.run([sys.executable, "-m", "alembic", "upgrade", target], cwd=BACKEND_ROOT, env=env, check=True, capture_output=True, text=True)
            migrate("b91f02a7c640")
            with closing(sqlite3.connect(database)) as connection, connection:
                for locale, title in [("en-US", "The Dark Knight"), ("tr-TR", "Kara Şövalye")]:
                    data = json.dumps({"tmdb_id": 155, "media_type": "movie", "title": title, "original_title": "The Dark Knight", "genres": ["Drama"]})
                    connection.execute("INSERT INTO localized_metadata VALUES (?,?,?,?)", ("movie:155", locale, data, "2026-01-01"))
            migrate("head")
            with closing(sqlite3.connect(database)) as connection:
                self.assertEqual(connection.execute("SELECT count(*) FROM catalog_entities").fetchone()[0], 1)
                self.assertEqual(connection.execute("SELECT count(*) FROM localized_metadata").fetchone()[0], 2)
                for term in ("dark", "sovalye"):
                    self.assertEqual(connection.execute("SELECT key FROM catalog_fts WHERE catalog_fts MATCH ?", (term,)).fetchone()[0], "movie:155")
            subprocess.run([sys.executable, "-m", "alembic", "check"], cwd=BACKEND_ROOT, env=env, check=True, capture_output=True, text=True)

    def test_recommendation_index_backfills_existing_catalog(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "recommendations.db"
            env = {**os.environ, "DATABASE_URL": f"sqlite:///{database}"}
            def migrate(target):
                subprocess.run([sys.executable, "-m", "alembic", "upgrade", target], cwd=BACKEND_ROOT, env=env, check=True, capture_output=True, text=True)
            migrate("c42e8a19d730")
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.execute("INSERT INTO catalog_entities (key,kind,tmdb_id,name,features,created_at,updated_at) VALUES (?,?,?,?,?,?,?)", ("movie:1", "movie", 1, "Existing", json.dumps({"genre_refs": [{"tmdb_id": 16}], "original_language": "ja"}), "2026-01-01", "2026-01-01"))
            migrate("head")
            with closing(sqlite3.connect(database)) as connection:
                self.assertEqual(set(connection.execute("SELECT term FROM catalog_features WHERE media_key='movie:1'").fetchall()), {("genre:16",), ("domain:anime",)})
                self.assertEqual(connection.execute("SELECT name FROM catalog_entities WHERE key='movie:1'").fetchone()[0], "Existing")
            subprocess.run([sys.executable, "-m", "alembic", "check"], cwd=BACKEND_ROOT, env=env, check=True, capture_output=True, text=True)
