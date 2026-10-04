"""Start an exact set of remote nodes after validating the entire selection."""

from .deploy import lab_path, named, start_node, verify_started


def start_selected(client, topology, names):
    """Start selected remote nodes; reject an incomplete selection before mutation."""
    if not names:
        raise ValueError("At least one node name is required")
    if any(not isinstance(name, str) or not name for name in names):
        raise ValueError("Selected node names must be nonempty strings")
    if len(names) != len(set(names)):
        raise ValueError("Selected node names must be unique")

    path = lab_path(topology)
    remote = named(client, path + "/nodes")
    missing = [name for name in names if name not in remote]
    if missing:
        raise RuntimeError(f"Missing nodes: {missing}; run eve apply first")
    unavailable = [(name, remote[name].get("status")) for name in names
                   if str(remote[name].get("status")) not in ("0", "2")]
    if unavailable:
        raise RuntimeError(f"Selected nodes are not stopped or running: {unavailable}")

    changed = []
    try:
        for name in names:
            node = remote[name]
            if str(node["status"]) == "2":
                continue
            start_node(client, path, node)
            changed.append(name)
    except RuntimeError as error:
        raise RuntimeError(f"start failed: {error}; accepted start requests: {changed}") from error
    verify_started(client, path, {remote[name]["id"]: name for name in names})
    return {"lab": topology["name"], "action": "start", "changed_nodes": changed}
