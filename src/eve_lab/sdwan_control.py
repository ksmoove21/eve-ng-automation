"""Prompt-safe Catalyst SD-WAN control-component console primitives."""
from dataclasses import dataclass
import re

from .device_console import Console


_CONFIG_PROMPT = r"(?m)^[A-Za-z0-9_.-]+\(config[^)]*\)#\s*$"
_EXEC_PROMPT = r"(?m)^[A-Za-z0-9_.-]+#\s*$"
_REJECTED = re.compile(
    r"(?im)^\s*(?:error:|failed:|syntax error:|invalid input|"
    r"%\s*(?:error|invalid|incomplete))")


@dataclass(frozen=True)
class ControlStage:
    name: str
    commands: tuple[str, ...]


def stages_from_plan(plan):
    """Validate and normalize compiled controller operations."""
    if not isinstance(plan, dict) or plan.get("adapter") != "viptela-control":
        raise ValueError("Expected a compiled viptela-control plan")
    result = []
    for item in plan.get("operations", []):
        if (not isinstance(item, dict)
                or not re.fullmatch(r"[a-z][a-z0-9-]*", str(item.get("name", "")))
                or item.get("mode") != "config-transaction"
                or item.get("commit") is not True
                or not isinstance(item.get("commands"), list)
                or not item["commands"]
                or any(not isinstance(command, str) or not command
                       or "\n" in command or "\r" in command
                       for command in item["commands"])):
            raise ValueError("Invalid compiled control-component stage")
        result.append(ControlStage(item["name"], tuple(item["commands"])))
    names = [item.name for item in result]
    if names not in (["identity", "vpn0"], ["identity", "vpn0", "vpn512"]):
        raise ValueError(
            "Control-component stages must be identity, vpn0, with optional vpn512")
    return tuple(result)


class ViptelaConsole(Console):
    """Apply one independently committed Viptela candidate transaction."""

    def configure_stage(self, stage, timeout=60):
        if not isinstance(stage, ControlStage):
            raise TypeError("stage must be a ControlStage")
        self.send("config")
        self.expect(_CONFIG_PROMPT, timeout=timeout, latest=True)
        for index, command in enumerate(stage.commands, start=1):
            self.send(command)
            output, _ = self.expect(
                _CONFIG_PROMPT, timeout=timeout, latest=True, redisplay=True)
            if _REJECTED.search(output):
                self.send("abort")
                self.expect(_EXEC_PROMPT, timeout=timeout, latest=True)
                raise RuntimeError(
                    "Viptela rejected " + stage.name + " command " +
                    str(index) + "; transaction aborted")
        self.send("commit and-quit")
        output, match = self.expect(
            r"(?m)^[A-Za-z0-9_.-]+(?:\(config[^)]*\))?#\s*$",
            timeout=max(timeout, 180), latest=True)
        if "(config" in match.group() or _REJECTED.search(output):
            self.send("abort")
            self.expect(_EXEC_PROMPT, timeout=timeout, latest=True)
            raise RuntimeError(
                "Viptela " + stage.name + " commit rejected; candidate aborted")

