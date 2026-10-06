"""Control-component initialization state and read-back tests."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

from eve_lab.device_console import ConsoleAuthenticationError
from eve_lab.sdwan_control import ControlStage
from eve_lab.sdwan_initialize import (
    DesiredStateMissing, _first_login, _read_state, ensure_stage, initialize_control, verify_stage,
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

    def test_manager_does_not_retry_rejected_credentials(self):
        console = MagicMock()
        console.login.side_effect = ConsoleAuthenticationError(
            "Console returned to login after one credential submission")
        state = {"version": 1, "nodes": {"MGR": {
            "eve_uuid": "same", "first_login": "pending",
            "completed_stages": []}}}
        with self.assertRaises(ConsoleAuthenticationError):
            _first_login(console, ("admin", "private", "enable"), state,
                         Path("state.json"), "MGR", "same", manager=True)
        console.login.assert_called_once()
        console.command.assert_not_called()

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


class CompiledPlanTests(unittest.TestCase):
    def test_check_uses_supplied_compiled_plan_without_r1_compiler(self):
        plan = {"schema": 1, "lab": "control-fixture", "node_operations": {
            "CTRL": {"adapter": "viptela-control", "personality": "controller",
                     "operations": [
                         {"name": "identity", "mode": "config-transaction",
                          "commands": ["system", "exit"], "commit": True},
                         {"name": "vpn0", "mode": "config-transaction",
                          "commands": ["vpn 0", "exit"], "commit": True},
                     ]},
        }}
        node = {"name": "CTRL", "status": "2", "url": "telnet://example:3000",
                "console": "telnet"}
        with patch("eve_lab.sdwan_initialize.named", return_value={"CTRL": node}), \
                patch("eve_lab.sdwan_initialize.load_topology") as load_topology, \
                patch("eve_lab.sdwan_initialize.load_and_compile") as compile_r1:
            result = initialize_control(
                MagicMock(), {"name": "control-fixture", "remote_folder": "/test"},
                Path("."), "default", "CTRL", check=True, compiled_plan=plan)
        self.assertEqual(result["stages"], ["identity", "vpn0"])
        load_topology.assert_not_called()
        compile_r1.assert_not_called()

    def test_rejects_compiled_plan_for_another_lab(self):
        with self.assertRaisesRegex(ValueError, "supplied topology"):
            initialize_control(
                MagicMock(), {"name": "control-fixture"}, Path("."), "default", "CTRL",
                compiled_plan={"schema": 1, "lab": "other", "node_operations": {}})


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
        with self.assertRaisesRegex(DesiredStateMissing, "missing desired"):
            verify_stage(console, stage)

    def test_stage_comparison_ignores_optional_single_token_quotes(self):
        stage = ControlStage("identity", (
            "system", 'organization-name "nwl-lab-sdwan"', "exit"))
        console = MagicMock()
        console.command.return_value = (
            "system\n organization-name nwl-lab-sdwan\n")
        self.assertEqual(verify_stage(console, stage)["missing"], 0)

    def test_identity_combines_normal_and_explicit_default_views(self):
        stage = ControlStage("identity", (
            "system", "vbond 10.1.0.2", "clock timezone UTC", "exit"))
        console = MagicMock()
        console.command.side_effect = [
            "system\n vbond 10.1.0.2\n",
            "system\n clock timezone UTC\n"]
        self.assertEqual(verify_stage(console, stage)["missing"], 0)
        self.assertEqual(
            [call.args[0] for call in console.command.call_args_list],
            ["show running-config system | nomore",
             "show running-config system | details | nomore"])

    def test_vpn0_combines_normal_and_explicit_default_views(self):
        stage = ControlStage("vpn0", (
            "vpn 0", "interface eth1", "tunnel-interface",
            "no allow-service all", "allow-service netconf", "exit",
            "exit", "exit"))
        console = MagicMock()
        console.command.side_effect = [
            "vpn 0\n interface eth1\n  tunnel-interface\n"
            "   allow-service netconf\n",
            "vpn 0\n interface eth1\n  tunnel-interface\n"
            "   no allow-service all\n   allow-service netconf\n",
        ]
        self.assertEqual(verify_stage(console, stage)["missing"], 0)
        self.assertEqual(
            [call.args[0] for call in console.command.call_args_list],
            ["show running-config vpn 0 | nomore",
             "show running-config vpn 0 | details | nomore"])

    def test_vpn0_requires_management_interface_absent(self):
        stage = ControlStage("vpn0", (
            "vpn 0", "no interface eth0", "interface eth1",
            "ip address 192.0.2.1/24", "exit", "exit"))
        console = MagicMock()
        console.command.return_value = (
            "vpn 0\n interface eth0\n interface eth1\n"
            "  ip address 192.0.2.1/24\n")
        with self.assertRaisesRegex(DesiredStateMissing, "missing desired"):
            verify_stage(console, stage)

    def test_matching_stage_is_not_reapplied(self):
        stage = ControlStage("identity", (
            "system", "host-name vManage1", "exit"))
        console = MagicMock()
        console.command.return_value = "system\n host-name vManage1\n"
        result, changed = ensure_stage(console, stage)
        self.assertFalse(changed)
        self.assertEqual(result["missing"], 0)
        console.configure_stage.assert_not_called()

    def test_only_confirmed_missing_stage_is_applied_once(self):
        stage = ControlStage("identity", (
            "system", "host-name vManage1", "exit"))
        console = MagicMock()
        console.command.side_effect = [
            "system\n", "system\n", "system\n host-name vManage1\n"]
        on_apply = MagicMock()
        result, changed = ensure_stage(
            console, stage, timeout=123, on_apply=on_apply)
        self.assertTrue(changed)
        self.assertEqual(result["missing"], 0)
        self.assertEqual(
            [call.kwargs["timeout"] for call in console.command.call_args_list],
            [123, 123, 123])
        on_apply.assert_called_once_with()
        console.configure_stage.assert_called_once_with(stage, timeout=123)

    def test_disabled_dhcp_is_scoped_to_transport_interface(self):
        stage = ControlStage("vpn0", (
            "vpn 0", "interface ge0/0", "no ip dhcp-client",
            "no ipv6 dhcp-client", "ip address 192.0.2.3/24", "exit", "exit"))
        console = MagicMock()
        console.command.return_value = (
            "vpn 0\n interface eth0\n  ip dhcp-client\n  ipv6 dhcp-client\n !\n"
            " interface ge0/0\n  ip address 192.0.2.3/24\n !\n")
        self.assertEqual(verify_stage(console, stage)["missing"], 0)
        console.command.assert_called_once()

    def test_enabled_dhcp_on_transport_is_rejected(self):
        stage = ControlStage("vpn0", (
            "vpn 0", "interface ge0/0", "no ip dhcp-client", "exit", "exit"))
        console = MagicMock()
        console.command.return_value = (
            "vpn 0\n interface eth0\n  no ip dhcp-client\n !\n"
            " interface ge0/0\n  ip dhcp-client\n !\n")
        with self.assertRaises(DesiredStateMissing):
            verify_stage(console, stage)

    def test_transport_failure_never_applies_stage(self):
        stage = ControlStage("identity", (
            "system", "host-name vManage1", "exit"))
        console = MagicMock()
        console.command.side_effect = RuntimeError("console timed out")
        with self.assertRaisesRegex(RuntimeError, "console timed out"):
            ensure_stage(console, stage, timeout=234)
        console.command.assert_called_once_with(
            "show running-config system | nomore", timeout=234)
        console.configure_stage.assert_not_called()


if __name__ == "__main__":
    unittest.main()
