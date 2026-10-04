"""Reconcile EVE-NG topology and manage lab lifecycle operations."""

from urllib.parse import quote
import time
import sys

from .client import EveAPIError
from .satellite import inspect_image
from .presentation import reconcile_presentation
from .topology import expand_links, interface_key, validate

STOP_TIMEOUT = 30


def wait_for_stopped(client, path, targets=None):
    """EVE-NG may acknowledge stop before the VM process has exited."""
    deadline = time.monotonic() + STOP_TIMEOUT
    while True:
        nodes = indexed(client.request("GET", path + "/nodes"))
        if targets is not None:
            if any(ident not in nodes or nodes[ident].get('name') != name for ident, name in targets.items()):
                raise RuntimeError('Selected node changed or disappeared while waiting for stop')
            nodes = {ident: nodes[ident] for ident in targets}
        if all(str(node.get("status")) == "0" for node in nodes.values()):
            return nodes
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return nodes
        time.sleep(min(1, remaining))


def lab_path(topology):
    folder = topology.get("remote_folder", "/").rstrip("/")
    return "labs" + quote(f"{folder}/{topology['name']}.unl", safe="/")


def ensure_folder(client, folder):
    """Create missing remote folder components and verify each result."""
    if folder in ("", "/"):
        return
    current = ""
    for component in folder.strip("/").split("/"):
        parent = current or "/"
        current += "/" + component
        endpoint = "folders" + quote(current, safe="/") + "/"
        try:
            client.request("GET", endpoint)
        except EveAPIError as error:
            if error.code != 404:
                raise
            client.request("POST", "folders", {"path": parent, "name": component})
            try:
                client.request("GET", endpoint)
            except EveAPIError as verification:
                raise RuntimeError(f"EVE did not create remote folder {current}") from verification

def plan(topology: dict, server: dict) -> dict:
    return {
        "lab": topology["name"], "server": server["url"],
        "remote_folder": topology.get("remote_folder", "/"),
        **{key: len(topology[key]) for key in ("nodes", "networks", "links")},
        "note": "Local validation and summary only; no remote comparison or changes.",
    }


def indexed(data):
    if isinstance(data, dict):
        return {str(key): value for key, value in data.items()}
    if isinstance(data, list):
        return {str(value.get("id", index)): value for index, value in enumerate(data)}
    raise RuntimeError("Expected an EVE-NG object collection")


def named(client, path):
    result = {}
    for ident, item in indexed(client.request("GET", path)).items():
        name = item["name"]
        if name in result:
            raise RuntimeError(f"Duplicate remote name {name} in {path}; resolve before applying")
        result[name] = {**item, "id": ident}
    return result


def check_settings(desired, actual):
    for key, value in desired.items():
        if str(actual.get(key)) != str(value):
            raise RuntimeError(
                f"Conflict on {desired['name']}.{key}: remote={actual.get(key)!r}, "
                f"requested={value!r}. Existing objects are not overwritten."
            )


def interfaces(client, path, node):
    data = client.request("GET", f"{path}/nodes/{node['id']}/interfaces")
    return indexed(data["ethernet"])


def resolve(ports, name):
    matches = [(ident, port) for ident, port in ports.items()
               if interface_key(port["name"]) == interface_key(name)]
    if len(matches) != 1:
        available = ", ".join(port["name"] for port in ports.values())
        raise RuntimeError(f"Cannot uniquely resolve interface {name}; available: {available}")
    return matches[0]


def check_link(client, path, link, nodes, networks, rewire=False):
    node = nodes[link["node"]]
    ident, port = resolve(interfaces(client, path, node), link["interface"])
    target = networks.get(link["network"], {}).get("id")
    current = str(port.get("network_id", 0))
    if current != "0" and current != target and not rewire:
        raise RuntimeError(f"Conflict: {link['node']} {link['interface']} already connects to network {current}")
    if current != target and str(node.get("status")) != "0":
        raise RuntimeError(f"Stop {link['node']} before adding interface connections")
    return ident, current


def check_direct_bridges(client, path, direct, nodes, networks):
    """Never hide a shared LAN when converting a visible bridge to a cable."""
    node_ports = {node["name"]: interfaces(client, path, node)
                  for node in nodes.values()}
    for name, attachments in direct:
        if name not in networks:
            continue
        expected = set()
        for link in attachments:
            if link["node"] in nodes:
                node = nodes[link["node"]]
                ident, _ = resolve(node_ports[node["name"]], link["interface"])
                expected.add((node["id"], ident))
        actual = set()
        for node in nodes.values():
            for ident, port in node_ports[node["name"]].items():
                if str(port.get("network_id")) == networks[name]["id"]:
                    actual.add((node["id"], ident))
        if actual - expected:
            raise RuntimeError(f"Direct link {name} has other attached interfaces; cannot hide a shared network")


def direct_bridge_is_exact(name, attachments, nodes, networks, node_ports):
    """Return true only when an existing bridge backs exactly one declared cable."""
    if name not in networks:
        return False
    expected = set()
    for link in attachments:
        if link["node"] not in nodes:
            return False
        node = nodes[link["node"]]
        ident, _ = resolve(node_ports[node["name"]], link["interface"])
        expected.add((node["id"], ident))
    actual = set()
    for node in nodes.values():
        for ident, port in node_ports[node["name"]].items():
            if str(port.get("network_id")) == networks[name]["id"]:
                actual.add((node["id"], ident))
    return len(expected) == 2 and actual == expected


def prune_objects(client, path, topology, changes):
    """Remove undeclared objects only after the desired topology was applied."""
    nodes = named(client, path + "/nodes")
    networks = named(client, path + "/networks")
    keep_nodes = {node["name"] for node in topology["nodes"]}
    keep_networks = {network["name"] for network in topology["networks"]}
    for name, node in nodes.items():
        if name not in keep_nodes and str(node.get("status")) == "0":
            client.request("DELETE", f"{path}/nodes/{node['id']}")
            changes.append(f"pruned node: {name}")
            if name in named(client, path + "/nodes"):
                raise RuntimeError(f"Server did not delete node {name}")
    nodes = named(client, path + "/nodes")
    desired_ports = set()
    for link in topology['links']:
        node = nodes[link['node']]
        ident, _ = resolve(interfaces(client, path, node), link['interface'])
        desired_ports.add((node['id'], ident))
    declared_networks = {network['name'] for network in topology['networks']}
    retained_network_ids = {network['id'] for name, network in networks.items() if name in declared_networks}
    for node in nodes.values():
        if str(node.get('status')) != '0':
            continue
        for ident, port in interfaces(client, path, node).items():
            if ((node['id'], ident) not in desired_ports and
                    str(port.get('network_id', 0)) in retained_network_ids):
                client.request('PUT', f"{path}/nodes/{node['id']}/interfaces", {ident: ''})
                changes.append(f"disconnected stale link: {node['name']} {port['name']}")
                if str(interfaces(client, path, node)[ident].get('network_id', 0)) != '0':
                    raise RuntimeError(f"Server did not disconnect {node['name']} {port['name']}")
    # Node deletion may also remove now-unused hidden networks.
    networks = named(client, path + "/networks")
    for name, network in networks.items():
        if name in keep_networks:
            continue
        attached = []
        for node in nodes.values():
            for ident, port in interfaces(client, path, node).items():
                if str(port.get("network_id")) == network["id"]:
                    attached.append((node, ident, port["name"]))
        if any(str(node.get('status')) != '0' for node, _, _ in attached):
            continue
        # EVE-NG deleteNetwork() unlinks attached interfaces before saving.
        # PUT to network 0 is invalid; interface DELETE is version-dependent.
        if name in named(client, path + "/networks"):
            client.request("DELETE", f"{path}/networks/{network['id']}")
        changes.append(f"pruned network: {name}")
        if name in named(client, path + "/networks"):
            raise RuntimeError(f"Server did not delete network {name}")
        for node, ident, port_name in attached:
            if str(interfaces(client, path, node)[ident].get("network_id")) != "0":
                raise RuntimeError(f"Server did not disconnect {node['name']} {port_name}")
            changes.append(f"disconnected {node['name']} {port_name} from {name}")


def preserve_active(client, path, topology, direct, nodes, networks):
    """Preserve running node settings/ports while reconciling stopped peers."""
    active = {name for name, node in nodes.items() if str(node.get('status')) != '0'}
    if not active:
        return topology, direct, []
    ports = {name: interfaces(client, path, nodes[name]) for name in active}
    node_ports = {name: ports.get(name) or interfaces(client, path, node)
                  for name, node in nodes.items()}
    by_id = {network['id']: name for name, network in networks.items()}
    live_networks = {by_id[str(port['network_id'])] for name in active for port in ports[name].values()
                     if str(port.get('network_id', 0)) in by_id}
    deferred = [{'kind': 'node', 'name': name, 'reason': 'Running node left unchanged'} for name in sorted(active)]
    result = {**topology}
    result['nodes'] = []
    declared = {node['name'] for node in topology['nodes']}
    fields = ('name', 'template', 'type', 'image', 'cpu', 'ram', 'ethernet', 'console', 'left', 'top', 'icon', 'cpulimit', 'sat')
    for desired in topology['nodes'] + [nodes[name] for name in sorted(active - declared)]:
        name = desired['name']
        result['nodes'].append({key: nodes[name][key] for key in fields if key in nodes[name]}
                               if name in active else dict(desired))
    desired_networks = {network['name']: dict(network) for network in topology['networks']}
    for name in sorted(live_networks):
        if name not in desired_networks:
            desired_networks[name] = {key: networks[name][key] for key in ('name', 'type', 'left', 'top') if key in networks[name]}
            deferred.append({'kind': 'network', 'name': name, 'reason': 'Deletion would disconnect a running node'})
        elif desired_networks[name]['type'] != networks[name]['type']:
            desired_networks[name]['type'] = networks[name]['type']
            deferred.append({'kind': 'network', 'name': name, 'reason': 'Type change would affect a running node'})
    result['networks'] = list(desired_networks.values())
    result['links'] = [dict(link) for link in topology['links'] if link['node'] not in active]
    result['links'] += [{'node': name, 'interface': port['name'], 'network': by_id[str(port['network_id'])]}
                        for name in sorted(active) for port in ports[name].values()
                        if str(port.get('network_id')) in by_id]
    # Stopped endpoints may be connected immediately. An existing exact bridge
    # may also be hidden while its endpoints run because visibility does not
    # alter connectivity. Any incomplete/shared/mismatched bridge stays deferred.
    ready_direct = []
    for name, links in direct:
        if name in live_networks or any(link['node'] in active for link in links):
            if direct_bridge_is_exact(
                    name, links, nodes, networks, node_ports):
                ready_direct.append((name, links))
            else:
                deferred.append({'kind': 'direct-link', 'name': name, 'reason': 'Direct-link attachment repair deferred until its running endpoints stop'})
        else:
            ready_direct.append((name, links))
    return result, ready_direct, deferred


def apply(client, topology, prune=True, root=None, server_name="default", image_inspector=inspect_image):
    validate(topology)
    topology, direct = expand_links(topology)
    placement_requirements = {
        node['name']: {key: node[key] for key in ('satellite', 'required_storage_gib', 'required_image_disks', 'required_image_disk_names') if key in node}
        for node in topology['nodes'] if 'satellite' in node
    }
    # Placement policy is controller-side metadata. EVE persists the selected
    # satellite as ``sat`` and has no storage-reservation field.
    topology = {**topology, 'nodes': [
        {**{key: value for key, value in node.items()
            if key not in ('satellite', 'required_storage_gib', 'required_image_disks', 'required_image_disk_names')},
         **({'sat': node['satellite']} if 'satellite' in node else {})}
        for node in topology['nodes']
    ]}
    path = lab_path(topology)
    folder = topology.get("remote_folder", "/").rstrip("/")
    folder_missing = False
    try:
        client.request("GET", "folders" + quote(folder, safe="/") + "/")
    except EveAPIError as error:
        if error.code != 404:
            raise
        folder_missing = True
    try:
        client.request("GET", path)
        exists = True
    except EveAPIError as error:
        if error.code != 404:
            raise
        exists = False
    nodes = named(client, path + "/nodes") if exists else {}
    networks = named(client, path + "/networks") if exists else {}
    deferred = []
    if prune:
        topology, direct, deferred = preserve_active(client, path, topology, direct, nodes, networks)
    # EVE exposes/persists CPU Limit for QEMU nodes. Native IOL node records do
    # not retain the template option, so they cannot participate in this policy.
    topology = {**topology, "nodes": [
        node if node['name'] in nodes and str(nodes[node['name']].get('status')) != '0' and prune
        else ({**node, 'cpulimit': 0} if node['type'] == 'qemu' else node)
        for node in topology['nodes']]}
    # Preflight templates/images and network types before creating anything.
    payloads = {}
    placements = {}
    cluster = client.request('GET', 'cluster') if placement_requirements else {}
    inspected_images = {}
    for node in topology["nodes"]:
        template = client.request("GET", "list/templates/" + quote(node["template"], safe=""))
        if template.get("type") != node["type"]:
            raise ValueError(f"Template type does not match {node['name']}")
        options = template["options"]
        if node["image"] not in options.get("image", {}).get("list", {}):
            raise ValueError(f"Image {node['image']} is not available for {node['template']}")
        if 'icon' in node and node['icon'] not in options.get('icon', {}).get('list', {}):
            raise ValueError(f"Icon {node['icon']} is not available for {node['template']}")
        if node['name'] in placement_requirements:
            requirement = placement_requirements[node['name']]
            satellite_id = node['sat']
            candidates = [item for item in cluster.values() if isinstance(item, dict)
                          and item.get('id') == satellite_id]
            if len(candidates) != 1:
                raise RuntimeError(f"Requested satellite {satellite_id} for {node['name']} is not present in EVE cluster inventory")
            satellite = candidates[0]
            if satellite.get('name') == 'master' or satellite_id == 0:
                raise RuntimeError(f"Requested placement for {node['name']} resolves to EVE manager; satellite placement is required")
            if satellite.get('online') != 1:
                raise RuntimeError(f"Requested satellite {satellite.get('name', satellite_id)} for {node['name']} is offline")
            if str(satellite_id) not in options.get('sat', {}).get('list', {}):
                raise RuntimeError(f"EVE template {node['template']} does not offer satellite {satellite_id} for {node['name']}")
            required_ram_kib = node.get('ram', 0) * 1024
            if satellite.get('live_ram') is None or int(satellite['live_ram']) < required_ram_kib:
                raise RuntimeError(f"Satellite {satellite.get('name', satellite_id)} lacks {node.get('ram')} MiB free RAM for {node['name']}")
            if satellite.get('cpu') is None or int(satellite['cpu']) < node.get('cpu', 0):
                raise RuntimeError(f"Satellite {satellite.get('name', satellite_id)} lacks {node.get('cpu')} vCPU capacity for {node['name']}")
            available_kib = int(satellite.get('disk', 0)) - int(satellite.get('disk_usage', 0))
            storage_gib = requirement.get('required_storage_gib')
            if storage_gib is not None and available_kib < storage_gib * 1024 * 1024:
                raise RuntimeError(f"Satellite {satellite.get('name', satellite_id)} lacks {storage_gib} GiB free storage for {node['name']}")
            placements[node['name']] = {
                'satellite_id': satellite_id,
                'satellite': satellite.get('name'),
                'available_ram_mib': int(satellite['live_ram']) // 1024,
                'available_storage_gib': available_kib // (1024 * 1024),
            }
            if root is None:
                raise RuntimeError('Satellite placement requires a workspace root so configured EVE SSH can preflight its image')
            required_names = requirement.get('required_image_disk_names')
            expected_disks = requirement.get('required_image_disks', len(required_names) if required_names else 1)
            image_key = (satellite.get('name'), node['image'], expected_disks,
                         tuple(required_names) if required_names else None)
            if image_key not in inspected_images:
                inspected_images[image_key] = image_inspector(
                    root, server_name, satellite.get('name'), node['image'], expected_disks,
                    satellite_key=satellite.get('pubkey'), **({'required_names': required_names}
                    if required_names else {}))
            readiness = inspected_images[image_key]
            placements[node['name']]['image_readiness'] = readiness
            if readiness.get('status') != 'READY':
                raise RuntimeError(
                    f"Satellite {satellite.get('name', satellite_id)} image {node['image']} is "
                    f"{readiness.get('status', 'INVALID')}: {readiness.get('reason', 'no readiness evidence')}")
        if prune and node["name"] in nodes and str(nodes[node["name"]].get("status")) != "0":
            continue
        defaults = {key: option["value"] for key, option in options.items()
                    if "value" in option and key != "uuid"}
        payloads[node["name"]] = {
            **defaults, "uuid": "", "left": 200, "top": 200,
            **node, "numberNodes": 1,
        }
    types = client.request("GET", "list/networks")
    for network in topology["networks"]:
        if network["type"] not in types:
            raise ValueError(f"Unavailable network type: {network['type']}")
    if not prune:
        check_direct_bridges(client, path, direct, nodes, networks)
    updates = []
    network_updates = []
    shrinking = {}
    for kind, existing in (("nodes", nodes), ("networks", networks)):
        for desired in topology[kind]:
            if desired["name"] in existing:
                actual = existing[desired["name"]]
                resources = {key: desired[key] for key in ("cpu", "ram", "ethernet", "console", "left", "top", "icon", "cpulimit", "sat")
                             if kind == "nodes" and key in desired
                             and str(desired[key]) != str(actual.get(key))}
                if kind == "networks":
                    resources = {key: desired[key] for key in ("type", "left", "top")
                                 if key in desired and str(desired[key]) != str(actual.get(key))}
                    if resources:
                        if not prune and any(str(node.get("status")) != "0" for node in nodes.values()):
                            raise RuntimeError("Stop all nodes before changing network settings")
                        network_updates.append((desired, actual["id"], resources))
                check_settings({key: value for key, value in desired.items() if key not in resources}, actual)
                if "ethernet" in resources and int(resources["ethernet"]) < int(actual["ethernet"]):
                    if not prune or actual.get("type") != "qemu":
                        raise RuntimeError(f"Cannot reduce {desired['name']} Ethernet count without pruning on a QEMU node")
                    ports = interfaces(client, path, actual)
                    if len(ports) != int(actual['ethernet']) or not all(key.isdigit() for key in ports):
                        raise RuntimeError(f"Cannot determine removable Ethernet ports for {desired['name']}")
                    removed = sorted(ports, key=int)[int(resources['ethernet']):]
                    for link in topology['links']:
                        if link['node'] == desired['name']:
                            port_id, _ = resolve(ports, link['interface'])
                            if port_id in removed:
                                raise RuntimeError(f"YAML link uses removed interface {desired['name']} {link['interface']}; update the link before reducing Ethernet count")
                    shrinking[desired['name']] = removed
                if resources and kind == "nodes":
                    if str(actual.get("status")) != "0":
                        raise RuntimeError(f"Stop {desired['name']} before changing node settings")
                    updates.append((desired, actual["id"], resources))
    growing = {desired["name"] for desired, _, resources in updates if "ethernet" in resources}
    for link in topology["links"]:
        if link["node"] in nodes:
            # Newly requested ports do not exist until after resizing. Existing
            # ports must still pass conflict checks before any writes.
            if link["node"] in growing:
                ports = interfaces(client, path, nodes[link["node"]])
                if not any(interface_key(port["name"]) == interface_key(link["interface"]) for port in ports.values()):
                    continue
            check_link(client, path, link, nodes, networks, rewire=prune)
    # Recheck activity before every write, including pruning and bridge edits.
    # A concurrent start can invalidate the protected-network snapshot.
    underlying = client
    active_snapshot = {(node['id'], name) for name, node in nodes.items() if str(node.get('status')) != '0'}
    class GuardedClient:
        def request(self, method, endpoint, payload=None):
            if exists and method in ('POST', 'PUT', 'DELETE'):
                current = named(underlying, path + '/nodes')
                active_now = {(node['id'], name) for name, node in current.items() if str(node.get('status')) != '0'}
                if active_now != active_snapshot:
                    raise RuntimeError('Node running state changed during apply; rerun to recompute safe changes')
            return underlying.request(method, endpoint, payload)
    presentation_report = {"declared": 0, "matched": 0}
    client = GuardedClient()
    changes = []
    try:
        if not exists:
            if folder_missing:
                ensure_folder(client, folder)
                changes.append(f"created folder: {folder}")
            client.request("POST", "labs", {
                "path": folder or "/", "name": topology["name"], "version": "1",
                "author": "eve", "description": topology.get("description", ""), "body": "",
            })
            changes.append("created lab")
        for desired, ident, settings in network_updates:
            if not prune and any(str(node.get("status")) != "0" for node in named(client, path + "/nodes").values()):
                raise RuntimeError("Stop all nodes before changing network settings")
            current = named(client, path + "/networks").get(desired["name"])
            if not current or current["id"] != ident:
                raise RuntimeError("Network changed during apply; retry")
            client.request("PUT", f"{path}/networks/{ident}", {"name": desired["name"], **settings})
            changes.append(f"updated network {desired['name']}: {settings}")
            networks = named(client, path + "/networks")
            check_settings(desired, networks[desired["name"]])
        for desired, ident, resources in updates:
            # Check again immediately before the write in case the node was started.
            current = named(client, path + "/nodes")[desired["name"]]
            if current["id"] != ident or str(current.get("status")) != "0":
                raise RuntimeError(f"Node {desired['name']} changed or started during apply; retry after stopping it")
            for port_id in shrinking.get(desired['name'], []):
                port = interfaces(client, path, current)[port_id]
                if str(port.get('network_id', 0)) != '0':
                    client.request('PUT', f"{path}/nodes/{ident}/interfaces", {port_id: ''})
                    changes.append(f"disconnected removed port: {desired['name']} {port['name']}")
                    if str(interfaces(client, path, current)[port_id].get('network_id', 0)) != '0':
                        raise RuntimeError(f"Server did not disconnect removed interface {port['name']}")
            # EVE-NG's edit() changes CPU/RAM without setting its modified flag.
            # Sending the unchanged name triggers persistence without a rename.
            client.request("PUT", f"{path}/nodes/{ident}", {"name": current["name"], **resources})
            changes.append(f"updated {desired['name']}: {resources}")
            nodes = named(client, path + "/nodes")
            check_settings(desired, nodes[desired["name"]])
            if desired['name'] in shrinking:
                remaining_ports = interfaces(client, path, nodes[desired['name']])
                if len(remaining_ports) != int(desired['ethernet']):
                    raise RuntimeError(f"Server did not resize interfaces for {desired['name']}")
        # Resizing may discard an unused hidden bridge; refresh before creating objects.
        networks = named(client, path + "/networks")
        for kind, existing in (("networks", networks), ("nodes", nodes)):
            for desired in topology[kind]:
                name = desired["name"]
                if name not in existing:
                    # Hidden bridges with no links are discarded on save by EVE-NG.
                    payload = payloads[name] if kind == "nodes" else {"visibility": 1, **desired}
                    client.request("POST", path + "/" + kind, payload)
                    changes.append(f"created {kind}: {name}")
                    existing.update(named(client, path + "/" + kind))
                    if name not in existing:
                        raise RuntimeError(f"Created {name} was not returned by server")
                    check_settings(desired, existing[name])
        # Resolve all links before writing any connections. New-node interface
        # names can only be checked after EVE-NG has created the node.
        pending = []
        for link in topology["links"]:
            ident, current = check_link(client, path, link, nodes, networks, rewire=prune)
            target = networks[link["network"]]["id"]
            if current != target:
                pending.append((link, ident, target))
        for link, ident, target in pending:
            node = nodes[link["node"]]
            endpoint = f"{path}/nodes/{node['id']}/interfaces"
            client.request("PUT", endpoint, {ident: target})
            changes.append(f"connected {link['node']} {link['interface']} to {link['network']}")
            _, port = resolve(interfaces(client, path, node), link["interface"])
            if str(port.get("network_id")) != target:
                raise RuntimeError("Server did not persist the requested connection")
        if prune:
            prune_objects(client, path, topology, changes)
            nodes = named(client, path + "/nodes")
            networks = named(client, path + "/networks")
        check_direct_bridges(client, path, direct, nodes, networks)
        hidden_names = (topology.get("presentation") or {}).get("hidden_networks", [])
        for name in [name for name, _ in direct] + hidden_names:
            network = networks.get(name)
            if network is None:
                raise RuntimeError(f"Declared hidden network disappeared: {name}")
            if str(network.get("visibility", 1)) != "0":
                client.request("PUT", f"{path}/networks/{network['id']}", {"visibility": 0})
                changes.append(
                    f"hid {'declared network' if name in hidden_names else 'direct-link bridge'}: {name}"
                )
                updated = named(client, path + "/networks")
                if name not in updated or str(updated[name].get("visibility")) != "0":
                    raise RuntimeError(f"Server did not hide network {name}")
        # Direct links are topology semantics. EVE requires an exclusive bridge
        # record as runtime backing, but every such record must remain hidden so
        # the native canvas presents one device-to-device cable.
        final_networks = named(client, path + "/networks")
        visible_backing = [name for name, _ in direct
                           if name not in final_networks
                           or str(final_networks[name].get("visibility", 1)) != "0"]
        if visible_backing:
            raise RuntimeError(f"Direct-link backing networks are not hidden: {visible_backing}")
        visible_declared = [name for name in hidden_names
                            if name not in final_networks
                            or str(final_networks[name].get("visibility", 1)) != "0"]
        if visible_declared:
            raise RuntimeError(f"Declared hidden networks are not hidden: {visible_declared}")
        presentation_report = reconcile_presentation(client, path, topology.get("presentation"), changes)
    except (RuntimeError, ValueError) as error:
        raise RuntimeError(
            f"Apply did not complete: {error}. Completed: {changes}. "
            "No rollback performed; inspect the lab and rerun after resolving the error."
        ) from error
    return {"lab": topology["name"], "path": path, "changes": changes, "deferred": deferred,
            "placement": placements,
            "presentation": {"direct_links": len(direct),
                             "backing_networks_hidden": len(direct),
                             "objects": presentation_report},
            "message": "Applied safe changes; deferred objects left unchanged" if deferred else ("Applied; no nodes started" if changes else "Already matches; no changes")}


def start_node(client, path, node):
    """Bound network-error retries by attached networks, checking state each time."""
    attempts = 3
    attempt = 0
    while attempt < attempts:
        attempt += 1
        try:
            client.request("GET", f"{path}/nodes/{node['id']}/start")
            if attempt > 1:
                print(f"{node['name']} started after {attempt} attempts. EVE reported network creation errors; "
                      "successful start does not verify bridge forwarding settings.", file=sys.stderr, flush=True)
            return
        except EveAPIError as error:
            if error.code != 400 or "Failed to create network (11)" not in str(error):
                raise
            if attempt == 1:
                # EVE can leave one newly created bridge behind per failed start.
                # Allow one attempt per attached network plus a final start,
                # while retaining a fixed upper limit for persistent failures.
                ports = interfaces(client, path, node)
                networks = {str(port.get('network_id')) for port in ports.values()
                            if str(port.get('network_id', 0)) not in ('0', '', 'None')}
                attempts = max(3, min(16, len(networks) + 1))
            print(f"{node['name']}: EVE network creation error on attempt {attempt}/{attempts}; "
                  "waiting and checking node status...", file=sys.stderr, flush=True)
            time.sleep(min(attempt, 3))
            current = indexed(client.request("GET", path + "/nodes")).get(node["id"])
            if current is None or current.get("name") != node["name"]:
                raise RuntimeError(f"Node {node['name']} changed or disappeared during start") from error
            if str(current.get("status")) == "2":
                print(f"{node['name']} is running despite the network error; inspect EVE bridge forwarding settings.",
                      file=sys.stderr, flush=True)
                return
            if str(current.get("status")) != "0":
                raise RuntimeError(f"Node {node['name']} has status {current.get('status')}; not retrying start") from error
            if attempt == attempts:
                raise RuntimeError(f"{node['name']} failed to start after {attempts} attempts; EVE still reports it stopped: {error}") from error



def verify_started(client, path, targets):
    """Require three consecutive running observations, not just an accepted start."""
    stable = 0
    current = {}
    for poll in range(31):
        current = indexed(client.request('GET', path + '/nodes'))
        if any(ident not in current or current[ident].get('name') != name for ident, name in targets.items()):
            raise RuntimeError('Selected node changed or disappeared during startup verification')
        active = all(str(current[ident].get('status')) == '2' for ident in targets)
        stable = stable + 1 if active else 0
        if stable >= 3:
            return
        if poll < 30:
            time.sleep(1)
    stopped = [name for ident, name in targets.items() if str(current[ident].get('status')) != '2']
    running = [name for ident, name in targets.items() if str(current[ident].get('status')) == '2']
    raise RuntimeError(f'Start verification failed: not running: {stopped}; currently running: {running}. '
                       'Inspect EVE wrapper logs; an accepted start request does not confirm a running VM')


def lifecycle(client, topology, action, node_name=None):
    if action not in ("start", "stop"):
        raise ValueError(f"Unsupported action: {action}")
    if action == "stop":
        return stop_all(client, topology, node_name=node_name)
    path = lab_path(topology)
    nodes = named(client, path + "/nodes")
    desired_nodes = [{"name": node_name}] if node_name is not None else topology["nodes"]
    missing = [node["name"] for node in desired_nodes if node["name"] not in nodes]
    if missing:
        raise RuntimeError(f"Missing nodes: {missing}; run eve apply first")
    completed = []
    try:
        for desired in desired_nodes:
            node = nodes[desired["name"]]
            if str(node.get("status")) == ("2" if action == "start" else "0"):
                continue
            start_node(client, path, node)
            completed.append(desired["name"])
    except RuntimeError as error:
        raise RuntimeError(f"{action} failed: {error}; accepted start requests: {completed}") from error
    if desired_nodes:
        verify_started(client, path, {nodes[item['name']]['id']: item['name'] for item in desired_nodes})
    return {"lab": topology["name"], "action": action, "changed_nodes": completed}


def request_stop(client, path, ident):
    """CE stop endpoint with the confirmed Pro automatic-stop route fallback."""
    endpoint = f"{path}/nodes/{ident}/stop"
    try:
        client.request("GET", endpoint)
    except EveAPIError as error:
        if error.code != 400 or "(60027)" not in str(error):
            raise
        # Pro 7.x Vue frontend supplies stopmode=3 (template-selected stop).
        client.request("GET", endpoint + "/stopmode=3")


def stop_all(client, topology, node_name=None):
    path = lab_path(topology)
    nodes = indexed(client.request("GET", path + "/nodes"))
    targets = None
    if node_name is not None:
        nodes = {ident: node for ident, node in nodes.items() if node.get('name') == node_name}
        if len(nodes) != 1:
            raise ValueError(f'Expected one remote node named {node_name}; found {len(nodes)}')
        targets = {ident: node['name'] for ident, node in nodes.items()}
    requested, completed, failures = {}, [], []
    for ident, node in nodes.items():
        if str(node.get("status")) == "0":
            continue
        try:
            request_stop(client, path, ident)
            requested[ident] = node["name"]
        except RuntimeError as error:
            failures.append(f"{node['name']} (ID {ident}): {error}")
    try:
        remaining = wait_for_stopped(client, path, targets=targets)
        completed = [name for ident, name in requested.items()
                     if ident in remaining and str(remaining[ident].get("status")) == "0"]
        active = [f"{node['name']} (ID {ident})" for ident, node in remaining.items()
                  if str(node.get("status")) != "0"]
        if active:
            failures.append(f"Nodes still active after {STOP_TIMEOUT}s: {active}")
    except RuntimeError as error:
        failures.append(f"Could not verify stopped state: {error}")
    if failures:
        raise RuntimeError(f"Stop incomplete: {'; '.join(failures)}. Completed nodes: {completed}. Stop requests accepted: {list(requested.values())}")
    return {"lab": topology["name"], "action": "stop", "changed_nodes": completed}


def lab_status(client, topology):
    path = lab_path(topology)
    nodes = client.request("GET", path + "/nodes")
    runtime_networks = indexed(client.request("GET", path + "/networks"))
    _, direct = expand_links(topology)
    backing_names = {name for name, _ in direct}
    presentation_networks = {
        ident: network for ident, network in runtime_networks.items()
        if network.get("name") not in backing_names
    }
    direct_links = [
        {"name": name,
         "from": {"node": attachments[0]["node"], "interface": attachments[0]["interface"]},
         "to": {"node": attachments[1]["node"], "interface": attachments[1]["interface"]}}
        for name, attachments in direct
    ]
    backing = [network for network in runtime_networks.values()
               if network.get("name") in backing_names]
    return {"lab": topology["name"], "nodes": nodes,
            "networks": presentation_networks, "links": direct_links,
            "runtime_backing": {
                "direct_link_networks": len(backing),
                "all_hidden": len(backing) == len(direct) and all(
                    str(network.get("visibility", 1)) == "0" for network in backing),
            }}


def delete(client, topology):
    """Delete the whole remote lab, including nodes not declared locally."""
    path = lab_path(topology)
    result = {"lab": topology["name"], "path": path, "deleted": False, "stopped_nodes": []}
    try:
        client.request("GET", path)
    except EveAPIError as error:
        if error.code != 404:
            raise
        return {**result, "message": "Lab already absent; no changes"}
    try:
        nodes = indexed(client.request("GET", path + "/nodes"))
        for ident, node in nodes.items():
            if str(node.get("status")) != "0":
                request_stop(client, path, ident)
                result["stopped_nodes"].append(node["name"])
        remaining = wait_for_stopped(client, path)
        if any(str(node.get("status")) != "0" for node in remaining.values()):
            raise RuntimeError("Some nodes are still active; lab was not deleted")
        client.request("DELETE", path)
        try:
            client.request("GET", path)
        except EveAPIError as error:
            if error.code != 404:
                raise
        else:
            raise RuntimeError("Server still reports the lab after deletion")
    except RuntimeError as error:
        raise RuntimeError(
            f"Delete did not complete: {error}. Stopped nodes: {result['stopped_nodes']}. "
            "Inspect remote state before retrying."
        ) from error
    return {**result, "deleted": True, "message": "Remote lab deleted; local files retained"}
