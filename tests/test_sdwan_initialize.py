"""Control-component initialization state and read-back tests."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

from eve_lab.sdwan_control import ControlStage
from eve_lab.sdwan_initialize import (
    _first_login, _read_state, verify_stage,
)


class StateTests(unittest.TestCase):
    def test_first_login_persists_pending_before_factory_transition(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            state = {"version": 1, "nodes": {}}
            console = MagicMock()
            console.command.return_value = "vManage 20.15.1\n"
            record = _first_login(
                console, ["admin", "private", "enable"], state, path,
                "MGR", "uuid-1")
            args, kwargs = console.login.call_args
            self.assertEqual(args, ("admin", "admin", "enable"))
            self.assertEqual(kwargs["new_password"], "private")
            self.assertTrue(callable(kwargs["on_password_submit"]))
            self.assertEqual(record["first_login"], "complete")
            self.assertEqual(_read_state(path)["nodes"]["MGR"]["eve_uuid"],
                             "uuid-1")

    def test_pending_same_uuid_uses_configured_credentials(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            state = {"version": 1, "nodes": {"MGR": {
                "eve_uuid": "uuid-1", "first_login": "pending",
                "completed_stages": []}}}
            console = MagicMock()
            console.command.return_value = "20.15.1\n"
            _first_login(console, ["admin", "private", "enable"], state,
                         path, "MGR", "uuid-1")
        console.login.assert_called_once_with(
            "admin", "private", "enable", new_password="private",
            vmanage_first_boot=False)

    def test_manager_reauthenticates_after_transient_first_boot_cli(self):
        console = MagicMock()
        console.command.side_effect = [RuntimeError("reboot"), "20.15.1"]
        state = {"version": 1, "nodes": {"MGR": {
            "eve_uuid": "same", "first_login": "pending",
            "completed_stages": []}}}
        with patch("eve_lab.sdwan_initialize._write_state"):
            record = _first_login(
                console, ("admin", "private", "enable"), state,
                Path("state.json"), "MGR", "same", manager=True)
        self.assertEqual(record["first_login"], "complete")
        self.assertEqual(console.login.call_count, 2)
        self.assertEqual(console.command.call_count, 2)

    def test_manager_retries_transient_configured_login(self):
        console = MagicMock()
        console.login.side_effect = [RuntimeError("boot"), None]
        console.command.return_value = "20.15.1"
        state = {"version": 1, "nodes": {"MGR": {
            "eve_uuid": "same", "first_login": "pending",
            "completed_stages": []}}}
        with patch("eve_lab.sdwan_initialize._write_state"):
            record = _first_login(
                console, ("admin", "private", "enable"), state,
                Path("state.json"), "MGR", "same", manager=True)
        self.assertEqual(record["first_login"], "complete")
        self.assertEqual(console.login.call_count, 2)
        console.command.assert_called_once_with("show version", timeout=60)


class DesiredStateTests(unittest.TestCase):
    def test_stage_requires_every_desired_readback_line(self):
        stage = ControlStage("identity", (
            "system", "host-name vManage1", "system-ip 172.16.1.101",
            "exit"))
        console = MagicMock()
        console.command.return_value = (
            "system\n host-name vManage1\n system-ip 172.16.1.101\n")
        self.assertEqual(verify_stage(console, stage)["missing"], 0)
        console.command.return_value = "system\n host-name vManage1\n"
        with self.assertRaisesRegex(RuntimeError, "missing desired"):
            verify_stage(console, stage)


if __name__ == "__main__":
    unittest.main()
