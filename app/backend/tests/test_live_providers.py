import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import providers.live as live
import providers.registry as registry


class LiveProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patches = [
            patch.object(registry, "LIVE_PROVIDER_ROOT", self.root),
            patch.object(live, "LIVE_PROVIDER_ROOT", self.root),
        ]
        for item in self.patches:
            item.start()
        registry.reload_registry()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        registry.reload_registry()
        self.temp.cleanup()

    def code(self, provider_id, name):
        return live.template_code(provider_id, name)

    def test_validate_reports_syntax_and_accepts_import_output(self):
        live.create_live_provider("syntax-test", "Syntax")
        live.save_draft("syntax-test", "not valid python !")
        result = live.validate_draft("syntax-test")
        self.assertFalse(result["valid"])
        self.assertIn("SyntaxError", result["errors"][0])

        live.save_draft(
            "syntax-test",
            'print("provider import")\n'
            + self.code("syntax-test", "Syntax"),
        )
        self.assertTrue(
            live.validate_draft("syntax-test")["valid"]
        )

    def test_validation_timeout_terminates_provider(self):
        live.create_live_provider("timeout-test", "Timeout")
        live.save_draft(
            "timeout-test",
            "import time\ntime.sleep(1)\n"
            + self.code("timeout-test", "Timeout"),
        )

        with patch.object(
            live,
            "VALIDATION_TIMEOUT_SECONDS",
            0.05,
        ):
            result = live.validate_draft("timeout-test")

        self.assertFalse(result["valid"])
        self.assertEqual(
            result["errors"],
            ["Provider validation timed out"],
        )

    def test_activation_hot_reloads_same_size_same_mtime_source(self):
        live.create_live_provider("reload-test", "AAAA")
        live.activate_draft("reload-test")
        active = self.root / "reload-test" / "active.py"
        old_mtime = active.stat().st_mtime_ns
        old_size = active.stat().st_size

        live.save_draft(
            "reload-test",
            self.code("reload-test", "BBBB"),
        )
        draft = self.root / "reload-test" / "draft.py"
        self.assertEqual(draft.stat().st_size, old_size)
        os.utime(draft, ns=(old_mtime, old_mtime))

        live.activate_draft("reload-test")
        self.assertEqual(
            registry.get_provider("reload-test").name,
            "BBBB",
        )

    def test_failed_activation_preserves_file_and_registry(self):
        live.create_live_provider("atomic-test", "Working")
        live.activate_draft("atomic-test")
        active = self.root / "atomic-test" / "active.py"
        previous = active.read_text()

        candidate = (
            'if __name__.startswith("_media_app_live_"):\n'
            '    raise RuntimeError("runtime import failed")\n'
            + self.code("atomic-test", "Broken")
        )
        live.save_draft("atomic-test", candidate)

        with self.assertRaises(live.LiveProviderValidationError):
            live.activate_draft("atomic-test")

        self.assertEqual(active.read_text(), previous)
        self.assertEqual(
            registry.get_provider("atomic-test").name,
            "Working",
        )

    def test_builtin_id_conflict_is_not_activation_success(self):
        directory = self.root / "mock-stream"
        (directory / "versions").mkdir(parents=True)
        (directory / "draft.py").write_text(
            self.code("mock-stream", "Conflict")
        )

        with self.assertRaises(live.LiveProviderValidationError):
            live.activate_draft("mock-stream")

        self.assertFalse((directory / "active.py").exists())
        self.assertEqual(
            registry.provider_sources()["mock-stream"],
            "builtin",
        )

    def test_factory_override_lifecycle_keeps_identity_and_factory(self):
        factory = registry.get_provider("mock-stream")
        created = live.create_factory_override("mock-stream")
        self.assertTrue(created["is_factory_override"])
        self.assertFalse(created["has_active"])
        self.assertIs(registry.get_provider("mock-stream"), factory)
        # Repeated create must not overwrite an edited draft.
        live.save_draft("mock-stream", self.code("mock-stream", "Override One"))
        self.assertIn("Override One", live.create_factory_override("mock-stream")["draft_code"])
        live.activate_draft("mock-stream")
        self.assertEqual(registry.get_provider("mock-stream").name, "Override One")
        live.save_draft("mock-stream", self.code("mock-stream", "Override Two"))
        live.activate_draft("mock-stream")
        version = live.list_versions("mock-stream")[0]
        live.rollback_provider("mock-stream", version)
        self.assertEqual(registry.get_provider("mock-stream").name, "Override One")
        reverted = live.revert_to_factory("mock-stream")
        self.assertEqual(reverted["implementation"], "builtin")
        self.assertFalse(reverted["has_active"])
        self.assertIs(registry.get_provider("mock-stream"), factory)
        self.assertTrue(reverted["versions"])
        registry.reload_registry()
        self.assertIs(registry.get_provider("mock-stream"), factory)

    def test_failed_override_leaves_factory_working(self):
        factory = registry.get_provider("mock-stream")
        live.create_factory_override("mock-stream")
        live.save_draft("mock-stream", "broken !!!")
        with self.assertRaises(live.LiveProviderValidationError):
            live.activate_draft("mock-stream")
        self.assertIs(registry.get_provider("mock-stream"), factory)
        live.save_draft("mock-stream", 'if __name__.startswith("_media_app_live_"):\n    raise RuntimeError("fail")\n' + self.code("mock-stream", "broken"))
        with self.assertRaises(live.LiveProviderValidationError):
            live.activate_draft("mock-stream")
        self.assertIs(registry.get_provider("mock-stream"), factory)
        self.assertFalse((self.root / "mock-stream" / "active.py").exists())

    def test_failed_revert_preserves_active_override(self):
        live.create_factory_override("mock-stream")
        live.save_draft("mock-stream", self.code("mock-stream", "Working Override"))
        live.activate_draft("mock-stream")
        active = self.root / "mock-stream" / "active.py"
        before = active.read_bytes()
        with patch.object(live, "reload_registry_if_factory", return_value=False):
            with self.assertRaises(live.LiveProviderError):
                live.revert_to_factory("mock-stream")
        self.assertEqual(active.read_bytes(), before)
        self.assertEqual(registry.get_provider("mock-stream").name, "Working Override")

    def test_delete_live_provider_removes_active_and_draft_but_not_factory(self):
        live.create_live_provider("remove-active", "Removable")
        live.activate_draft("remove-active")
        self.assertIsNotNone(registry.get_provider("remove-active"))
        live.delete_live_provider("remove-active")
        self.assertFalse((self.root / "remove-active").exists())
        self.assertIsNone(registry.get_provider("remove-active"))
        live.create_live_provider("remove-draft", "Draft")
        live.delete_live_provider("remove-draft")
        self.assertFalse((self.root / "remove-draft").exists())
        with self.assertRaises(live.LiveProviderNotFound):
            live.delete_live_provider("remove-draft")
        live.create_factory_override("mock-stream")
        with self.assertRaises(live.LiveProviderConflict):
            live.delete_live_provider("mock-stream")
        self.assertTrue((self.root / "mock-stream" / "draft.py").exists())
        self.assertIsNotNone(registry.get_provider("mock-stream"))

    def test_failed_delete_restores_active_and_registry(self):
        live.create_live_provider("keep-active", "Working")
        live.activate_draft("keep-active")
        with patch.object(live, "reload_registry", side_effect=RuntimeError("reload failed")):
            with self.assertRaises(RuntimeError):
                live.delete_live_provider("keep-active")
        self.assertTrue((self.root / "keep-active" / "active.py").exists())
        self.assertIsNotNone(registry.get_provider("keep-active"))

    def test_rollback_updates_active_and_draft(self):
        live.create_live_provider("rollback-test", "Version One")
        live.activate_draft("rollback-test")
        live.save_draft(
            "rollback-test",
            self.code("rollback-test", "Version Two"),
        )
        state = live.activate_draft("rollback-test")
        version = state["versions"][0]

        rolled_back = live.rollback_provider(
            "rollback-test",
            version,
        )

        self.assertEqual(
            registry.get_provider("rollback-test").name,
            "Version One",
        )
        self.assertEqual(
            rolled_back["active_code"],
            rolled_back["draft_code"],
        )

    def test_failed_rollback_without_active_cleans_candidate(self):
        live.create_live_provider("bad-rollback", "Draft")
        directory = self.root / "bad-rollback"
        version = directory / "versions" / "bad.py"
        version.write_text(
            'raise RuntimeError("bad version")\n'
            + self.code("bad-rollback", "Bad"),
        )

        with self.assertRaises(live.LiveProviderError):
            live.rollback_provider("bad-rollback", "bad.py")

        self.assertFalse((directory / "active.py").exists())

    def test_settings_require_existing_provider_and_object_file(self):
        with self.assertRaises(live.LiveProviderNotFound):
            live.get_settings("missing-provider")

        live.create_live_provider("settings-test", "Settings")
        settings_path = self.root / "settings-test" / "settings.json"
        settings_path.write_text("[]")
        with self.assertRaises(live.LiveProviderError):
            live.get_settings("settings-test")
