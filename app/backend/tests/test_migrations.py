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
                }.issubset(tables)
            )
            self.assertEqual(revision, "b91f02a7c640")
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
