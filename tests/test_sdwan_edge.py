"""IOS XE Catalyst SD-WAN cEdge transaction tests."""
import re
import unittest
from unittest.mock import MagicMock

from eve_lab.sdwan_edge import (
    CedgeConsole, EdgeStage, missing_desired_commands, stages_from_edge_plan,
)


class EdgePlanTests(unittest.TestCase):
    def plan(self):
        return {"adapter": "c8000v-sdwan", "operations": [
            {"name": "controller-mode", "mode": "privileged-exec",
             "command": "controller-mode enable", "one_shot": True},
            *[{"name": name, "mode": "config-transaction",
               "commands": ["system", "exit"], "commit": True}
              for name in ("identity", "transport", "service-lan")],
        ]}

    def test_normalizes_owner_baseline_stage_order(self):
        self.assertEqual([item.name for item in stages_from_edge_plan(self.plan())],
                         ["identity", "transport", "service-lan"])

    def test_rejects_reordered_or_multiline_stage(self):
        plan = self.plan()
        plan["operations"][2]["name"] = "service-lan"
        with self.assertRaises(ValueError):
            stages_from_edge_plan(plan)

    def test_desired_readback_ignores_exit_and_no_shutdown_only(self):
        stages = (EdgeStage("identity", (
            "hostname EDGE", "organization-name org", "no shutdown", "exit")),)
        output = 'hostname EDGE\n organization-name "org"\n'
        self.assertEqual(missing_desired_commands(output, stages), ())
        self.assertEqual(missing_desired_commands("hostname EDGE\n", stages),
                         ("organization-name org",))


class EdgeConsoleTests(unittest.TestCase):
    def console(self, responses):
        console = CedgeConsole(MagicMock())
        console.expect = MagicMock(side_effect=[
            (text, re.search(r"[^\n]+#", text)) for text in responses])
        return console

    def test_commits_stage_and_returns_to_exec(self):
        console = self.console([
            "EDGE(config)#", "EDGE(config)#", "EDGE(config)#",
            "Commit complete\nEDGE(config)#", "EDGE#"])
        console.configure_stage(EdgeStage("identity", ("system", "exit")))
        sent = [call.args[0] for call in console.channel.sendall.call_args_list]
        self.assertEqual(sent, [
            "config-transaction\r", "system\r", "exit\r", "commit\r",
            "end\r"])
        self.assertTrue(console.expect.call_args_list[-1].kwargs["redisplay"])

    def test_rejection_aborts_without_commit(self):
        console = self.console([
            "EDGE(config)#", "% Invalid input\nEDGE(config)#", "EDGE#"])
        with self.assertRaisesRegex(RuntimeError, "command 1"):
            console.configure_stage(EdgeStage("transport", ("bad",)))
        sent = [call.args[0] for call in console.channel.sendall.call_args_list]
        self.assertEqual(sent, ["config-transaction\r", "bad\r", "abort\r"])


if __name__ == "__main__":
    unittest.main()
