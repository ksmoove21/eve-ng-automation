"""Load a lab definition independently of its target server."""

from pathlib import Path
import re
import hashlib

import yaml


def interface_key(name: str) -> str:
    key = name.lower().replace(" ", "")
    aliases = (
        (r"^(gigabitethernet|gi|g)(?=\d)", "gi"),
        (r"^(fastethernet|fa|f)(?=\d)", "fa"),
        (r"^(ethernet|et|e)(?=\d)", "e"),
    )
    for pattern, replacement in aliases:
        key = re.sub(pattern, replacement, key)
    return key


def validate_folder(folder):
    if not isinstance(folder, str) or not folder.startswith("/") or any(
        part in (".", "..") for part in folder.split("/")
    ):
        raise ValueError("remote_folder must be an absolute EVE-NG folder without . or ..")


def load_lab_target(root: Path, lab: str, remote_folder=None) -> dict:
    """Resolve only the remote path; node/link edits must not block stopping."""
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]*", lab):
        raise ValueError("Lab names may contain letters, digits, underscores, and hyphens")
    if remote_folder is None:
        try:
            document = yaml.safe_load((root / "labs" / lab / "topology.yaml").read_text())
        except (OSError, yaml.YAMLError) as error:
            raise ValueError("Cannot read lab folder from YAML; use --remote-folder /path to target the remote lab directly") from error
        if not isinstance(document, dict):
            raise ValueError("Cannot read lab folder from YAML; use --remote-folder /path")
        remote_folder = document.get("remote_folder", "/")
    validate_folder(remote_folder)
    return {"name": lab, "remote_folder": remote_folder}


def expand_links(topology):
    """Compile direct links into private bridges and endpoint attachments."""
    networks = list(topology.get("networks", []))
    links, direct = [], []
    for link in topology.get("links", []):
        if not isinstance(link, dict) or not ({"from", "to"} & link.keys()):
            links.append(link)
            continue
        if set(link) - {"name", "from", "to"} or not {"from", "to"} <= link.keys():
            raise ValueError("Direct links require from/to endpoints and optional name")
        ends = [link["from"], link["to"]]
        for end in ends:
            if not isinstance(end, dict) or set(end) != {"node", "interface"} or any(
                not isinstance(value, str) or not value.strip() for value in end.values()
            ):
                raise ValueError("Direct link endpoints require node and interface strings")
        key = repr(sorted((end["node"], interface_key(end["interface"])) for end in ends))
        name = link.get("name", "direct-" + hashlib.sha256(key.encode()).hexdigest()[:12])
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Direct link name must be a nonempty string")
        networks.append({"name": name, "type": "bridge"})
        attachments = [{**end, "network": name} for end in ends]
        links.extend(attachments)
        direct.append((name, attachments))
    return {**topology, "networks": networks, "links": links}, direct


def validate(topology: dict):
    for field in ("nodes", "networks", "links"):
        if not isinstance(topology.get(field), list):
            raise ValueError(f"Topology {field} must be a list")
    topology, _ = expand_links(topology)
    validate_folder(topology.get("remote_folder", "/"))
    allowed = {
        "nodes": {"name", "template", "type", "image", "cpu", "ram", "ethernet", "console", "left", "top", "icon",
                  "satellite", "required_storage_gib", "required_image_disks"},
        "networks": {"name", "type", "left", "top"},
        "links": {"node", "interface", "network"},
    }
    for kind, fields in allowed.items():
        if not isinstance(topology.get(kind), list):
            raise ValueError(f"Topology {kind} must be a list")
        for item in topology[kind]:
            if not isinstance(item, dict) or set(item) - fields:
                raise ValueError(f"Invalid or unsupported fields in {kind}: {item}")
    names = {}
    for kind, required in (("nodes", ("name", "template", "type", "image")), ("networks", ("name", "type"))):
        names[kind] = set()
        for item in topology[kind]:
            for field in required:
                if not isinstance(item.get(field), str) or not item[field].strip():
                    raise ValueError(f"{kind}: {field} must be a nonempty string")
            if item["name"] in names[kind]:
                raise ValueError(f"Duplicate {kind} name: {item['name']}")
            names[kind].add(item["name"])
    for node in topology["nodes"]:
        if "icon" in node and (not isinstance(node["icon"], str) or not node["icon"].strip()
                               or any(c in node["icon"] for c in ("/", "\\", "\n", "\r"))):
            raise ValueError("icon must be an EVE icon basename")
        if node["type"] not in ("qemu", "iol"):
            raise ValueError("Deployment currently supports QEMU and IOL nodes only")
        if "/" in node["image"] or "\\" in node["image"]:
            raise ValueError("image must be a directory basename, not a path")
        for field in ("cpu", "ram", "ethernet"):
            if field in node and (type(node[field]) is not int or node[field] < 1):
                raise ValueError(f"{node['name']}: {field} must be a positive integer")
        if "satellite" in node and (type(node["satellite"]) is not int or node["satellite"] < 1):
            raise ValueError(f"{node['name']}: satellite must be a positive EVE satellite ID; manager placement is not allowed")
        if "required_storage_gib" in node and (
                type(node["required_storage_gib"]) is not int or node["required_storage_gib"] < 1):
            raise ValueError(f"{node['name']}: required_storage_gib must be a positive integer")
        if "required_image_disks" in node and (
                type(node["required_image_disks"]) is not int or node["required_image_disks"] < 1):
            raise ValueError(f"{node['name']}: required_image_disks must be a positive integer")
    endpoints = set()
    for link in topology["links"]:
        if any(not isinstance(link.get(field), str) or not link[field] for field in allowed["links"]):
            raise ValueError("Each link needs node, interface, and network strings")
        if link["node"] not in names["nodes"] or link["network"] not in names["networks"]:
            raise ValueError(f"Unknown node or network in link: {link}")
        endpoint = (link["node"], interface_key(link["interface"]))
        if endpoint in endpoints:
            raise ValueError(f"Interface connected more than once: {endpoint}")
        endpoints.add(endpoint)


def load_topology(root: Path, lab: str, scenario=None) -> dict:
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]*", lab):
        raise ValueError("Lab names may contain letters, digits, underscores, and hyphens")
    if scenario is not None and not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]*", scenario):
        raise ValueError("Scenario names may contain letters, digits, underscores, and hyphens")
    filename = Path("topology.yaml") if scenario is None else Path("scenarios") / (scenario + ".yaml")
    topology = yaml.safe_load((root / "labs" / lab / filename).read_text())
    if not isinstance(topology, dict) or topology.get("name") != lab:
        raise ValueError("Topology name must match its lab directory for every scenario")
    validate(topology)
    return topology
