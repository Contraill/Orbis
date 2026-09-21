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
            self.assertEqual(revision, "ab8f4f782e31")
