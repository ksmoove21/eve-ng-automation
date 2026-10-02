"""Scoped live EVE account/lab authorization guards."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import yaml

from eve_lab.live_guard import enforce_live_guard, remote_lab_path


class LiveGuardTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.topology = {"name": "guarded-lab", "remote_folder": "/team"}
        self.base = self.root / "labs" / "guarded-lab"
        self.base.mkdir(parents=True)

    def tearDown(self):
        self.temporary.cleanup()

    def write(self, **updates):
        document = {
            "version": 1,
            "eve_username": "automation-user",
            "remote_lab": "/team/guarded-lab.unl",
            **updates,
        }
        (self.base / "live-guard.yaml").write_text(yaml.safe_dump(document))

    def test_exact_account_and_remote_lab_pass(self):
        self.write()
        result = enforce_live_guard(
            self.root, self.topology, {"username": "automation-user"})
        self.assertEqual(result["eve_username"], "automation-user")
        self.assertEqual(result["remote_lab"], "/team/guarded-lab.unl")

    def test_wrong_account_fails_closed_without_aliases(self):
        self.write()
        for username in ("retired-user", "Automation-User", None):
            with self.subTest(username=username), self.assertRaisesRegex(
                    ValueError, "username"):
                enforce_live_guard(
                    self.root, self.topology, {"username": username})

    def test_wrong_remote_folder_fails_closed(self):
        self.write()
        changed = {**self.topology, "remote_folder": "/other"}
        with self.assertRaisesRegex(ValueError, "remote lab path"):
            enforce_live_guard(
                self.root, changed, {"username": "automation-user"})

    def test_missing_guard_preserves_other_lab_behavior(self):
        self.assertIsNone(enforce_live_guard(
            self.root, self.topology, {"username": "unrestricted-existing-user"}))

    def test_schema_is_strict(self):
        self.write(retired_aliases=["old-lab"])
        with self.assertRaisesRegex(ValueError, "exactly"):
            enforce_live_guard(
                self.root, self.topology, {"username": "automation-user"})

    def test_root_remote_path(self):
        self.assertEqual(
            remote_lab_path({"name": "fixture", "remote_folder": "/"}),
            "/fixture.unl")


if __name__ == "__main__":
    unittest.main()
