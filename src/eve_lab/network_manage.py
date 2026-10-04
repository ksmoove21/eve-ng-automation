"""Materialize one exact existing EVE Pro direct-link network via its GUI API.

EVE Pro can persist node interface assignments without creating the running
bridge/endpoint stitches. This command replays the network Manage form for one
Git-declared direct link, preserving every current bridge option and port.
Runtime bridge/tap proof remains a separate acceptance check.
"""

import argparse
import json
from pathlib import Path

import yaml

from .client import EveClient
from .config import load_server
from .deploy import lab_path
from .topology import interface_key


_BRIDGE_OPTIONS = ("smart", "vlan8021ad", "native_vlan", "pnet_out",
                   "l2filter_lldp", "l2filter_stp", "l2filter_cisco",
                   "l2filter_lacp")


def _port_identity(port):
    if not isinstance(port, dict):
        raise ValueError("EVE network Manage returned an invalid port")
    node = port.get("NodeName")
    name = port.get("IfName")
    if not isinstance(node, str) or not isinstance(name, str):
        raise ValueError("EVE network Manage port lacks node or interface")
    return node, interface_key(name)


def compile_manage_payload(topology, link_name, network_id, observed):
    """Require exact declared endpoints and preserve the complete GUI form."""
    links = [link for link in topology.get("links", [])
             if link.get("name") == link_name]
    if len(links) != 1:
        raise ValueError("Select exactly one Git-declared direct link")
    link = links[0]
    expected = {(end["node"], interface_key(end["interface"]))
                for end in (link["from"], link["to"])}
    ports = observed.get("interfaces")
    if (not isinstance(observed.get("name"), str) or
            observed.get("type") != "bridge" or observed.get("count") != 2 or
            not isinstance(ports, list) or len(ports) != 2 or
            len(expected) != 2 or {_port_identity(port) for port in ports} != expected):
        raise ValueError("EVE direct-link network differs from Git endpoints")
    for key in _BRIDGE_OPTIONS:
        if key not in observed:
            raise ValueError("EVE network Manage lacks bridge option " + key)
    body = {"network": str(network_id),
            "smart": str(observed["smart"]),
            "vlan8021ad": str(observed["vlan8021ad"]),
            "native_vlan": str(observed["native_vlan"]),
            "port": {}}
    for key in _BRIDGE_OPTIONS[3:]:
        body[key] = str(observed[key])
    for index, port in enumerate(ports):
        if (not str(port.get("NodeId", "")).isdigit() or
                not str(port.get("IfId", "")).isdigit() or
                not str(port.get("VlanId", "")).isdigit()):
            raise ValueError("EVE network Manage port IDs are invalid")
        body["port"][str(index)] = {
            "NodeId": str(port["NodeId"]), "NodeName": port["NodeName"],
            "IfId": str(port["IfId"]), "IfName": port["IfName"],
            "Vlan": str(port["VlanId"])}
    return body


def manage_network(client, topology, link_name, network_id, apply=False):
    path = lab_path(topology)
    ident = str(network_id)
    if not ident.isdecimal() or int(ident) < 1:
        raise ValueError("Select one positive EVE network ID")
    endpoint = path + "/networks/" + ident
    before = client.request("GET", endpoint)
    payload = compile_manage_payload(topology, link_name, ident, before)
    summary = {"link": link_name, "eve_network": before["name"], "id": int(ident),
               "ports": [{"node": port["NodeName"], "interface": port["IfName"]}
                         for port in before["interfaces"]]}
    if not apply:
        return {**summary, "status": "checked", "runtime_proof": "not-requested"}
    client.request("PUT", path + "/network/manage", payload)
    after = client.request("GET", endpoint)
    if compile_manage_payload(topology, link_name, ident, after) != payload:
        raise RuntimeError("EVE network Manage changed declared link intent")
    return {**summary, "status": "manage-accepted",
            "runtime_proof": "verify bridge and endpoint stitches separately"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("topology", type=Path)
    parser.add_argument("--link", required=True, help="Exact Git link name")
    parser.add_argument("--id", type=int, required=True, help="Existing EVE network ID")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--server", default="default")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    topology = yaml.safe_load(args.topology.read_text())
    server = load_server(args.root, args.server)
    client = EveClient(server["url"])
    client.login(server["username"], server["password"])
    try:
        result = manage_network(client, topology, args.link, args.id, args.apply)
        print(json.dumps(result))
    finally:
        client.logout()


if __name__ == "__main__":
    main()
