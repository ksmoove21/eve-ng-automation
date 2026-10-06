"""Control-component stage and console transaction tests."""
import re
import unittest
from unittest.mock import MagicMock

from eve_lab.sdwan_control import ControlStage, ViptelaConsole, stages_from_plan


class ControlPlanTests(unittest.TestCase):
    def test_normalizes_exact_ordered_compiled_stages(self):
        plan = {"adapter": "viptela-control", "operations": [
            {"name": name, "mode": "config-transaction",
             "commands": ["system", "exit"], "commit": True}
            for name in ("identity", "vpn0", "vpn512")
        ]}
        self.assertEqual([stage.name for stage in stages_from_plan(plan)],
                         ["identity", "vpn0", "vpn512"])

    def test_accepts_controller_without_vpn512(self):
        plan = {"adapter": "viptela-control", "operations": [
            {"name": name, "mode": "config-transaction",
             "commands": ["system", "exit"], "commit": True}
            for name in ("identity", "vpn0")
        ]}
        self.assertEqual([stage.name for stage in stages_from_plan(plan)],
                         ["identity", "vpn0"])

    def test_rejects_reordered_or_multiline_commands(self):
        for operations in (
            [{"name": "vpn0", "mode": "config-transaction",
              "commands": ["vpn 0"], "commit": True}],
            [{"name": name, "mode": "config-transaction",
              "commands": ["bad\ncommit" if name == "vpn0" else "system"],
              "commit": True} for name in ("identity", "vpn0", "vpn512")],
        ):
            with self.assertRaises(ValueError):
                stages_from_plan({"adapter": "viptela-control",
                                  "operations": operations})


class ViptelaConsoleTests(unittest.TestCase):
    def console(self, responses):
        console = ViptelaConsole(MagicMock())
        console.expect = MagicMock(side_effect=[
            (text, re.search(r"[^\n]+#", text)) for text in responses])
        return console

    def test_commits_one_stage(self):
        console = self.console([
            "vManage(config)#", "vManage(config)#", "vManage(config)#",
            "Commit complete\nvManage#"])
        console.configure_stage(ControlStage("identity", ("system", "exit")))
        self.assertEqual([call.args[0] for call in console.channel.sendall.call_args_list],
                         ["config\r", "system\r", "exit\r", "commit and-quit\r"])

    def test_rejection_aborts_without_commit(self):
        console = self.console([
            "vManage(config)#", "% Invalid input\nvManage(config)#", "vManage#"])
        with self.assertRaisesRegex(RuntimeError, "command 1"):
            console.configure_stage(ControlStage("vpn0", ("bad",)))
        sent = [call.args[0] for call in console.channel.sendall.call_args_list]
        self.assertEqual(sent, ["config\r", "bad\r", "abort\r"])
        self.assertNotIn("commit and-quit\r", sent)


if __name__ == "__main__":
    unittest.main()

