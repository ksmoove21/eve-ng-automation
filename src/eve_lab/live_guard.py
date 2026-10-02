"""Optional per-lab authorization guard for live EVE operations."""

from pathlib import Path

import yaml


_FIELDS = {"version", "eve_username", "remote_lab"}


def remote_lab_path(topology):
    folder = topology.get("remote_folder", "/").rstrip("/")
    return (folder + "/" + topology["name"] + ".unl") if folder else (
        "/" + topology["name"] + ".unl")


def enforce_live_guard(root, topology, server):
    """Fail closed when a lab has an exact account/path authorization contract."""
    base = (Path(root) / "labs" / topology["name"]).resolve()
    path = (base / "live-guard.yaml").resolve()
    if not path.is_relative_to(base):
        raise ValueError("Live guard must remain inside the lab directory")
    if not path.exists():
        return None
    if not path.is_file():
        raise ValueError("Live guard must be a regular file")
    document = yaml.safe_load(path.read_text())
    if not isinstance(document, dict) or set(document) != _FIELDS:
        raise ValueError("Live guard requires exactly version, eve_username, and remote_lab")
    if document["version"] != 1:
        raise ValueError("Live guard version must be 1")
    for field in ("eve_username", "remote_lab"):
        if not isinstance(document[field], str) or not document[field].strip():
            raise ValueError("Live guard " + field + " must be a nonempty string")
    actual_user = server.get("username")
    if actual_user != document["eve_username"]:
        raise ValueError(
            "Live guard rejected EVE username for " + topology["name"] +
            "; select the explicitly authorized account")
    actual_lab = remote_lab_path(topology)
    if actual_lab != document["remote_lab"]:
        raise ValueError(
            "Live guard rejected remote lab path for " + topology["name"] +
            "; do not create or target an alternate lab")
    return {
        "eve_username": actual_user,
        "remote_lab": actual_lab,
        "guard": str(path),
    }
