import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from unittest.mock import Mock
from fastapi.testclient import TestClient

from tv.webos import renewal
from main import app


class RenewalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patches = [
            patch.object(renewal, "ROOT", self.root),
            patch.object(renewal, "DEVICES", self.root / "devices.json"),
            patch.object(renewal, "ARES_HOME", self.root / "ares-home"),
            patch.object(renewal, "TOKENS", self.root / "tokens"),
        ]
        for item in self.patches:
            item.start()
        self.now = datetime(2026, 10, 6, tzinfo=timezone.utc)

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_register_checkin_and_private_file(self):
        identity = "a" * 32
        renewal.register(identity, "livingroom")
        self.assertTrue(renewal.record_checkin(identity))
        self.assertFalse(renewal.record_checkin(identity))
        row = renewal.local_status()[0]
        self.assertEqual(row["target"], "livingroom")
        self.assertIsNotNone(row["last_checkin"])
        self.assertEqual(self.root.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.root / "devices.json").stat().st_mode & 0o777, 0o600)
        with self.assertRaises(ValueError):
            renewal.register("bad", "livingroom")
        with self.assertRaises(ValueError):
            renewal.register(identity, "bad;command")

    def test_renewal_due_at_30_days_and_not_before(self):
        row = {"last_successful_renewal": self.now.isoformat(), "last_attempt": self.now.isoformat(), "status": "ok"}
        self.assertFalse(renewal.is_due(row, self.now + timedelta(days=29)))
        self.assertTrue(renewal.is_due(row, self.now + timedelta(days=30)))

    def test_offline_retry_success_and_expired_state(self):
        identity = "b" * 32
        with patch.object(renewal, "utcnow", return_value=self.now):
            renewal.register(identity, "bedroom")
        with patch.object(renewal, "_renew", return_value=("retry_pending", "device_offline_or_renewal_unverified")) as command:
            self.assertEqual(renewal.run_due(identity, self.now), 1)
            self.assertEqual(renewal.run_due(identity, self.now + timedelta(hours=23)), 0)
            self.assertEqual(command.call_count, 1)
        with patch.object(renewal, "_renew", return_value=("ok", None)):
            self.assertEqual(renewal.run_due(identity, self.now + timedelta(days=1)), 1)
        self.assertEqual(renewal.local_status()[0]["status"], "ok")
        self.assertEqual(renewal.run_due(identity, self.now + timedelta(days=2)), 0)
        with patch.object(renewal, "_renew", return_value=("expired_manual_recovery_required", "developer_mode_expired")):
            self.assertEqual(renewal.run_due(identity, self.now + timedelta(days=31)), 1)
        self.assertEqual(renewal.local_status()[0]["status"], "expired_manual_recovery_required")
        self.assertEqual(renewal.run_due(identity, self.now + timedelta(days=40)), 0)

    def test_current_cli_command_is_argument_vector_and_legacy_fallback(self):
        with patch.object(renewal.subprocess, "run", return_value=Mock(returncode=0)) as run:
            self.assertEqual(renewal._launch("livingroom", "current"), "launched")
            self.assertEqual(run.call_args.args[0], ["ares-launch", "com.palmdts.devmode", "-p", "extend=true", "-d", "livingroom"])
            self.assertEqual(renewal._launch("livingroom", "legacy"), "launched")
            self.assertEqual(run.call_args.args[0], ["ares-extend-dev", "-d", "livingroom"])

    def test_verified_current_cli_success_and_no_token_exposure(self):
        identity = "c" * 32
        renewal.register(identity, "livingroom")
        token = "privateToken1234567890"
        self.assertNotIn(token, str(renewal.local_status()))
        with patch.object(renewal, "_token", return_value=token), \
             patch.object(renewal, "_remaining", side_effect=[timedelta(days=5), timedelta(days=41)]), \
             patch.object(renewal.shutil, "which", side_effect=lambda name: "/bin/ares-launch" if name == "ares-launch" else None), \
             patch.object(renewal, "_launch", return_value="launched") as launch:
            self.assertEqual(renewal._renew(identity, "livingroom"), ("ok", None))
            launch.assert_called_once_with("livingroom", "current")

    def test_successful_command_without_lifetime_increase_is_not_success(self):
        with patch.object(renewal, "_token", return_value="privateToken1234567890"), \
             patch.object(renewal, "_remaining", return_value=timedelta(days=5)), \
             patch.object(renewal.shutil, "which", side_effect=lambda name: "/bin/ares-launch" if name == "ares-launch" else None), \
             patch.object(renewal, "_launch", return_value="launched"), \
             patch.object(renewal.time, "sleep"), \
             patch.object(renewal, "_session_request", return_value={"result": "success"}):
            self.assertEqual(renewal._renew("d" * 32, "livingroom")[0], "retry_pending")

    def test_expired_session_skips_renewal(self):
        with patch.object(renewal, "_token", return_value="privateToken1234567890"), \
             patch.object(renewal, "_remaining", return_value=timedelta(0)), \
             patch.object(renewal, "_launch") as launch:
            self.assertEqual(renewal._renew("d" * 32, "livingroom")[0], "expired_manual_recovery_required")
            launch.assert_not_called()

    def test_legacy_and_reset_fallbacks_require_verified_lifetime(self):
        token = "privateToken1234567890"
        with patch.object(renewal, "_token", return_value=token), \
             patch.object(renewal, "_remaining", side_effect=[timedelta(days=4), timedelta(days=40)]), \
             patch.object(renewal.shutil, "which", side_effect=lambda name: "/bin/ares-extend-dev" if name == "ares-extend-dev" else None), \
             patch.object(renewal, "_launch", return_value="launched") as launch:
            self.assertEqual(renewal._renew("f" * 32, "livingroom"), ("ok", None))
            launch.assert_called_once_with("livingroom", "legacy")
        with patch.object(renewal, "_token", return_value=token), \
             patch.object(renewal, "_remaining", side_effect=[timedelta(days=4), timedelta(days=40)]), \
             patch.object(renewal.shutil, "which", return_value=None), \
             patch.object(renewal, "_session_request", return_value={"result": "success"}) as request:
            self.assertEqual(renewal._renew("f" * 32, "livingroom"), ("ok", None))
            request.assert_called_once_with("ResetDevModeSession", token)

    def test_session_response_parsing(self):
        with patch.object(renewal, "_session_request", return_value={"result": "success", "errorMsg": "999:58:40"}):
            self.assertEqual(renewal._remaining("privateToken1234567890"), timedelta(hours=999, minutes=58, seconds=40))

    def test_offline_launch_does_not_try_token_reset(self):
        with patch.object(renewal, "_token", return_value="privateToken1234567890"), \
             patch.object(renewal, "_remaining", return_value=timedelta(days=4)), \
             patch.object(renewal.shutil, "which", side_effect=lambda name: "/bin/ares-launch" if name == "ares-launch" else None), \
             patch.object(renewal, "_launch", return_value="unreachable"), \
             patch.object(renewal, "_session_request") as request:
            self.assertEqual(renewal._renew("f" * 32, "livingroom")[0], "retry_pending")
            request.assert_not_called()

    def test_capture_token_stays_private(self):
        identity = "e" * 32
        renewal.register(identity, "livingroom")
        token = "privateToken1234567890"
        with patch.object(renewal.subprocess, "run", return_value=Mock(returncode=0, stdout=token)):
            renewal.capture_session_token(identity)
        path = self.root / "tokens" / identity
        self.assertEqual(path.read_text(), token)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(token, str(renewal.local_status()))

    def test_public_checkin_and_health_reveal_no_private_device_data(self):
        with patch("api.tv_webos.record_checkin"), patch("api.tv_webos.run_due"):
            client = TestClient(app)
            health = client.get("/api/health", headers={"Origin": "null"})
            self.assertEqual(health.status_code, 200)
            self.assertEqual(health.headers.get("access-control-allow-origin"), "*")
            checkin = client.post("/api/tv/webos/check-in", content="d" * 32,
                                  headers={"Content-Type": "text/plain", "Origin": "null"})
            self.assertEqual(checkin.status_code, 204)
            self.assertEqual(checkin.headers.get("access-control-allow-origin"), "*")
            self.assertEqual(checkin.content, b"")


if __name__ == "__main__":
    unittest.main()
