"""Transactional IOS XE Catalyst SD-WAN cEdge console primitives."""
from dataclasses import dataclass
import re

from .device_console import Console


_CONFIG_PROMPT = r"(?m)^[A-Za-z0-9_.-]+\(config[^)]*\)#\s*$"
_EXEC_PROMPT = r"(?m)^[A-Za-z0-9_.-]+#\s*$"
_ANY_PROMPT = r"(?m)^[A-Za-z0-9_.-]+(?:\(config[^)]*\))?#\s*$"
_REJECTED = re.compile(
    r"(?im)^\s*(?:error:|failed:|syntax error:|invalid input|commit failed|"
    r"aborted:|%\s*(?:error|invalid|incomplete|ambiguous))")


@dataclass(frozen=True)
class EdgeStage:
    name: str
    commands: tuple[str, ...]


def stages_from_edge_plan(plan):
    """Validate and normalize the compiled owner-baseline cEdge stages."""
    if not isinstance(plan, dict) or plan.get("adapter") != "c8000v-sdwan":
        raise ValueError("Expected a compiled c8000v-sdwan plan")
    result = []
    for item in plan.get("operations", []):
        if item.get("mode") != "config-transaction":
            continue
        if (not re.fullmatch(r"[a-z][a-z0-9-]*", str(item.get("name", "")))
                or item.get("commit") is not True
                or not isinstance(item.get("commands"), list)
                or not item["commands"]
                or any(not isinstance(command, str) or not command
                       or "\n" in command or "\r" in command
                       for command in item["commands"])):
            raise ValueError("Invalid compiled cEdge stage")
        result.append(EdgeStage(item["name"], tuple(item["commands"])))
    if [item.name for item in result] != [
            "identity", "transport", "service-lan"]:
        raise ValueError(
            "cEdge stages must be identity, transport, service-lan")
    return tuple(result)


def _normalized_config(output):
    return "\n".join(" ".join(line.replace('"', '').split())
                     for line in output.splitlines())


def missing_desired_commands(output, stages):
    """Return desired configuration lines absent from SD-WAN read-back."""
    normalized = _normalized_config(output)
    omitted = {"exit", "no shutdown"}
    desired = [" ".join(command.replace('"', '').split())
               for stage in stages for command in stage.commands
               if command not in omitted]
    return tuple(command for command in desired
                 if not re.search(r"(?m)^\s*" + re.escape(command) + r"\s*$",
                                  normalized))


class CedgeConsole(Console):
    """Apply independently committed IOS XE SD-WAN config transactions."""

    def configure_stage(self, stage, timeout=90):
        if not isinstance(stage, EdgeStage):
            raise TypeError("stage must be an EdgeStage")
        self.send("config-transaction")
        self.expect(_CONFIG_PROMPT, timeout=timeout, latest=True)
        for index, command in enumerate(stage.commands, start=1):
            self.send(command)
            output, _ = self.expect(
                _CONFIG_PROMPT, timeout=timeout, latest=True, redisplay=True)
            if _REJECTED.search(output):
                self.send("abort")
                self.expect(_EXEC_PROMPT, timeout=timeout, latest=True)
                raise RuntimeError(
                    "cEdge rejected " + stage.name + " command " +
                    str(index) + "; transaction aborted")
        self.send("commit")
        output, match = self.expect(
            _ANY_PROMPT, timeout=max(timeout, 300), latest=True)
        if _REJECTED.search(output):
            if "(config" in match.group():
                self.send("abort")
                self.expect(_EXEC_PROMPT, timeout=timeout, latest=True)
            raise RuntimeError(
                "cEdge " + stage.name + " commit rejected")
        if "(config" in match.group():
            self.send("end")
            self.expect(_EXEC_PROMPT, timeout=timeout, latest=True,
                        redisplay=True)
