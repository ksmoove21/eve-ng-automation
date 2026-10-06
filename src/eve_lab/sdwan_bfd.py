"""Evaluate BFD against explicit transport intent, including required extensions."""
from dataclasses import dataclass
from ipaddress import IPv4Address
from typing import Mapping, Sequence

@dataclass(frozen=True)
class EdgeTransport:
    system_ip: str
    site_id: int
    colors: tuple[str, ...]

    def __post_init__(self):
        IPv4Address(self.system_ip)
        if not self.colors or len(set(self.colors)) != len(self.colors):
            raise ValueError("Each edge requires distinct intended transport colors")

Path = tuple[str, str, str]

def expected_paths(local: EdgeTransport, edges: Sequence[EdgeTransport],
                   allowed_color_pairs: set[tuple[str, str]]) -> tuple[set[Path], set[Path]]:
    """Return required and isolated paths between sites using intended colors.

    Include intended TLOC extension colors even before they become operational.
    Do not derive intended colors from current device output.
    """
    if len({edge.system_ip for edge in edges}) != len(edges):
        raise ValueError("Duplicate edge system IP")
    if local not in edges:
        raise ValueError("Local edge is absent from intent")
    required, isolated = set(), set()
    for remote in edges:
        if remote.site_id == local.site_id:
            continue
        for local_color in local.colors:
            for remote_color in remote.colors:
                path = (remote.system_ip, local_color, remote_color)
                target = required if (local_color, remote_color) in allowed_color_pairs else isolated
                target.add(path)
    return required, isolated

def parse_bfd_sessions(output: str) -> dict[Path, str]:
    """Parse IOS XE SD-WAN BFD table; reject conflicting duplicate rows."""
    sessions = {}
    for line in output.splitlines():
        tokens = line.split()
        if len(tokens) < 9:
            continue
        try:
            IPv4Address(tokens[0])
        except ValueError:
            continue
        path, state = (tokens[0], tokens[3], tokens[4]), tokens[2].lower()
        if path in sessions and sessions[path] != state:
            raise ValueError(f"Conflicting BFD states for {path}")
        sessions[path] = state
    return sessions

def evaluate_bfd(observed: Mapping[Path, str], required: set[Path], isolated: set[Path]) -> dict:
    """Required paths must be up; isolated paths may be missing or down.

    Isolated paths that are up and unknown peers/colors violate declared intent.
    """
    if required & isolated:
        raise ValueError("A path cannot be both required and isolated")
    issues = [(*path, observed.get(path, "missing")) for path in sorted(required)
              if observed.get(path) != "up"]
    unexpected = sorted(set(observed) - required - isolated)
    violations = sorted(path for path in isolated if observed.get(path) == "up")
    return {"required_count": len(required), "required_issues": issues,
            "unexpected_paths": unexpected, "isolation_violations": violations,
            "observed_isolated_paths": sorted(set(observed) & isolated),
            "passed": not issues and not unexpected and not violations}
