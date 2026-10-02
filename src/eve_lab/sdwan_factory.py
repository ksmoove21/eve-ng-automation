"""Resumable factory-to-ready orchestration for Catalyst SD-WAN labs.

Private intent drives the build. Runtime one-shot correlation remains in an
ignored ``.state`` file under that private workspace.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from ipaddress import ip_interface
import json
import os
from pathlib import Path
import re
import socket
import ssl
import time
from urllib.parse import urlsplit

import paramiko

from .config import load_server
from .deploy import apply, delete, lab_path, lifecycle, named
from .device_console import Console, credentials
from .initialize import _open_telnet_console, initialize, telnet_console_url
from .sdwan_api import ManagerApi
from .sdwan_control import ViptelaConsole
from .sdwan_edge import (CedgeConsole, certificate_sha256,
                         missing_desired_commands, stages_from_edge_plan)
from .sdwan_initialize import (
    _read_state as read_control_state,
    _state_path as control_state_path,
    _write_state as write_control_state,
    ensure_manager_ca_live, initialize_control, qualify_manager)
from .sdwan_intent import load_and_compile
from .sdwan_manager import (
    certificate_is_installed, control_component_record,
    control_component_record_by_uuid, ensure_fabric_settings,
    wait_for_control_component_csr)
from .sdwan_pki import (install_controller_root, manager_ca_certificate,
                        sign_csr_on_manager, _enter_shell, _leave_shell,
                        _shell_command)
from .topology import load_topology


_CONTROL = ("MANAGER1", "VALIDATOR1", "CONTROLLER1")
_UNDERLAY = ("DC1", "BIZ-INTERNET", "PUBLIC-INTERNET", "SW2", "SW3", "SW4")
_EDGES = ("CEDGE-S2", "CEDGE-S3", "CEDGE-S4")
_PROMPT = r"(?m)^[A-Za-z0-9_.-]+#\s*$"


def _now():
    return datetime.now(timezone.utc).isoformat()


def _atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def correlate_single_new(before, after):
    """Return the only newly-created UUID and record, or fail closed."""
    prior = {str(item.get("uuid", "")).strip() for item in before
             if str(item.get("uuid", "")).strip()}
    current = {str(item.get("uuid", "")).strip(): item for item in after
               if str(item.get("uuid", "")).strip()}
    created = set(current) - prior
    if len(created) != 1:
        raise RuntimeError("PAYG inventory set difference produced " +
                           str(len(created)) +
                           " new identities; expected exactly one")
    uuid = created.pop()
    return uuid, current[uuid]


class FactoryLedger:
    """Generation-bound durable one-shot state."""

    def __init__(self, path):
        self.path = Path(path)
        self.value = (json.loads(self.path.read_text()) if self.path.exists()
                      else {"version": 1, "generations": {}})
        if (not isinstance(self.value, dict)
                or self.value.get("version") != 1
                or not isinstance(self.value.get("generations"), dict)):
            raise ValueError("Invalid SD-WAN factory state")

    def bind(self, nodes):
        identities = {name: str(nodes[name].get("uuid", ""))
                      for name in _CONTROL + _EDGES}
        if any(not value for value in identities.values()):
            raise RuntimeError("Every control/edge node requires an EVE UUID")
        generation = hashlib.sha256(json.dumps(
            identities, sort_keys=True).encode()).hexdigest()[:24]
        entry = self.value["generations"].setdefault(generation, {
            "created_at": _now(), "node_uuids": identities, "edges": {}})
        if entry.get("node_uuids") != identities:
            raise RuntimeError("Factory generation UUID correlation changed")
        self.value["active_generation"] = generation
        self.save()
        return entry

    def save(self):
        _atomic_json(self.path, self.value)


def _required_environment():
    missing = [name for name in (
        "CISCO_USERNAME", "CISCO_PASSWORD", "CISCO_ENABLE_SECRET")
        if not os.environ.get(name)]
    if missing:
        raise ValueError("Missing required private environment variables: " +
                         ", ".join(missing))


def preflight(root, lab, topology=None):
    """Compile and validate the complete factory contract without live access."""
    root = Path(root)
    topology = topology or load_topology(root, lab)
    compiled = load_and_compile(root, lab, topology)
    nodes = {item["name"]: item for item in topology["nodes"]}
    if set(nodes) != set(_CONTROL + _UNDERLAY + _EDGES):
        raise ValueError("Factory topology node set does not match R1 contract")
    if [item["name"] for item in topology.get("networks", [])] != [
            "CLOUD0-VPN512"]:
        raise ValueError("Factory requires CLOUD0-VPN512 as its only visible network")
    if nodes["MANAGER1"].get("cpu") != 22:
        raise ValueError("MANAGER1 must declare 22 vCPU")
    expected_sequence = [
        "transport-underlay", "manager-install-and-baseline",
        "manager-enterprise-ca-and-certificate",
        "validator-baseline-certificate", "controller-baseline-certificate",
        "control-fabric-validation", "payg-correlation",
        "edge-controller-mode-cli-baseline-root-trust-activation",
        "multi-edge-control-validation", "destroyed-state-rebuild"]
    if compiled.get("sequence") != expected_sequence:
        raise ValueError("Compiled SD-WAN sequence differs from factory contract")
    for name in _CONTROL + _UNDERLAY + _EDGES:
        if name not in compiled["node_operations"]:
            raise ValueError("Compiled intent omitted " + name)
    return {"check": True, "lab": lab, "node_count": len(nodes),
            "control_nodes": list(_CONTROL), "underlay_nodes": list(_UNDERLAY),
            "edge_nodes": list(_EDGES),
            "visible_networks": ["CLOUD0-VPN512"],
            "sequence": expected_sequence,
            "one_shot_guards": ["controller-mode", "payg-generation",
                                "payg-activation"]}


@dataclass
class FactoryContext:
    client: object
    topology: dict
    root: Path
    server_name: str
    compiled: dict
    nodes: dict
    ledger: FactoryLedger
    generation: dict

    @property
    def lab(self):
        return self.topology["name"]

    @property
    def control_state_path(self):
        return control_state_path(self.root, self.lab)

    def refresh_nodes(self):
        self.nodes = named(self.client, lab_path(self.topology) + "/nodes")
        return self.nodes

    def control_plan(self, name):
        return self.compiled["node_operations"][name]

    def management_address(self, name):
        return str(ip_interface(
            self.control_plan(name)["desired"]["vpn512_address"]).ip)


def _reauth(context):
    """Renew the native-console EVE session at long-running phase boundaries."""
    server = load_server(context.root, context.server_name)
    context.client.login(server["username"], server["password"], html5=False)


@contextmanager
def _eve_console(context, name, console_type=Console, boot_timeout=300):
    _reauth(context)
    node = context.refresh_nodes().get(name)
    if node is None or str(node.get("status")) != "2":
        raise RuntimeError(name + " must be running")
    url = telnet_console_url(node)
    if url is None:
        raise RuntimeError(name + " lacks a Telnet console")
    server = load_server(context.root, context.server_name, auth="ssh")
    ssh = paramiko.SSHClient()
    channel = None
    try:
        ssh.load_system_host_keys()
        ssh.connect(server.get("ssh_host") or urlsplit(server["url"]).hostname,
                    username=server["ssh_username"], password=server["ssh_password"],
                    timeout=10, auth_timeout=10, banner_timeout=10,
                    allow_agent=False, look_for_keys=False)
        channel = _open_telnet_console(ssh, url.port)
        yield console_type(channel, boot_timeout=boot_timeout)
    finally:
        if channel is not None:
            channel.close()
        ssh.close()


@contextmanager
def _pinned_management_console(context, name, console_type=ViptelaConsole,
                               boot_timeout=300):
    state = read_control_state(context.control_state_path)
    record = state.get("nodes", {}).get(name)
    if not isinstance(record, dict) or not record.get("management_ssh_sha256"):
        raise RuntimeError(name + " management SSH pin is absent")
    login = credentials(context.root)
    sock = socket.create_connection((context.management_address(name), 22), timeout=10)
    transport = paramiko.Transport(sock)
    channel = None
    try:
        transport.start_client(timeout=10)
        observed = hashlib.sha256(
            transport.get_remote_server_key().asbytes()).hexdigest()
        if observed != record["management_ssh_sha256"]:
            raise RuntimeError(name + " management SSH host key changed")
        transport.auth_password(login[0], login[1])
        channel = transport.open_session(timeout=10)
        channel.get_pty()
        channel.invoke_shell()
        console = console_type(channel, boot_timeout=boot_timeout)
        console.expect(_PROMPT, timeout=120, wake=True, latest=True)
        yield console
    finally:
        if channel is not None:
            channel.close()
        transport.close()


def _wait_activity(api, activity_id, operation, timeout=900):
    if not activity_id:
        return
    deadline = time.monotonic() + timeout
    while True:
        status = api.activity_status(activity_id)
        if status.completed:
            if not status.successful:
                raise RuntimeError(operation + " activity ended in " + status.status)
            return
        if time.monotonic() >= deadline:
            raise RuntimeError(operation + " activity timed out")
        time.sleep(15)


def _manager_api(context, timeout=45):
    address = context.management_address("MANAGER1")
    state = context.generation.setdefault("manager_api", {})
    certificate_path = context.root / ".state" / (context.lab + "-manager-https.pem")
    pem = ssl.get_server_certificate((address, 8443), timeout=10)
    fingerprint = hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest()
    expected = state.get("https_sha256")
    if expected is not None and expected != fingerprint:
        raise RuntimeError("Manager HTTPS certificate changed within this generation")
    certificate_path.parent.mkdir(parents=True, exist_ok=True)
    certificate_path.write_text(pem)
    decoded = ssl._ssl._test_decode_cert(str(certificate_path.resolve()))
    common_names = [value for group in decoded.get("subject", ())
                    for key, value in group if key == "commonName"]
    if len(common_names) != 1:
        raise RuntimeError("Manager HTTPS certificate lacks one common name")
    state.update({"https_sha256": fingerprint, "server_name": common_names[0]})
    context.ledger.save()
    api = ManagerApi(address, port=8443, certificate=certificate_path,
                     server_name=common_names[0], timeout=timeout)
    api.qualify(os.environ["CISCO_USERNAME"], os.environ["CISCO_PASSWORD"])
    return api


def _install_control_root(context, name, root_certificate):
    state = read_control_state(context.control_state_path)
    record = state["nodes"][name]
    digest = hashlib.sha256(
        (root_certificate.replace("\r\n", "\n").strip() + "\n").encode()
    ).hexdigest()
    if record.get("enterprise_root_installed_sha256") == digest:
        return False
    address = context.management_address(name)
    login = credentials(context.root)
    sock = socket.create_connection((address, 22), timeout=10)
    transport = paramiko.Transport(sock)
    channel = None
    try:
        transport.start_client(timeout=10)
        observed = hashlib.sha256(
            transport.get_remote_server_key().asbytes()).hexdigest()
        expected = record.get("management_ssh_sha256")
        if expected is not None and expected != observed:
            raise RuntimeError(name + " management SSH host key changed")
        transport.auth_password(login[0], login[1])
        if expected is None:
            record["management_ssh_sha256"] = observed
            write_control_state(context.control_state_path, state)
        channel = transport.open_session(timeout=10)
        channel.get_pty()
        channel.invoke_shell()
        console = ViptelaConsole(channel, boot_timeout=300)
        console.expect(_PROMPT, timeout=120, wake=True, latest=True)
        install_controller_root(
            console, root_certificate, subject_marker="nwl-lab-sdwan-CA")
    finally:
        if channel is not None:
            channel.close()
        transport.close()
    record["enterprise_root_installed_sha256"] = digest
    write_control_state(context.control_state_path, state)
    return True


def _sign_on_manager(context, csr, name):
    with _pinned_management_console(context, "MANAGER1") as console:
        return sign_csr_on_manager(console, csr, name=name)


def _install_manager_certificate(context, api):
    state = read_control_state(context.control_state_path)
    record = state["nodes"]["MANAGER1"]
    device_ip = context.control_plan("MANAGER1")["desired"]["system_ip"]
    inventory = control_component_record(
        api, device_ip=device_ip, personality="vmanage")
    root_hash = str(inventory.get("rootCertHash", "")).strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", root_hash):
        raise RuntimeError("Manager enterprise root hash is unavailable")
    if certificate_is_installed(inventory, root_hash=root_hash):
        record.update({"manager_control_certificate": "installed",
                       "manager_root_hash": root_hash})
        write_control_state(context.control_state_path, state)
        return False
    if record.get("manager_certificate_install_attempted"):
        _wait_activity(api, record.get("manager_certificate_activity_id"),
                       "Manager certificate")
    else:
        csr = api.generate_csr(device_ip)
        certificate = _sign_on_manager(context, csr, "manager-control")
        record.update({
            "manager_csr_sha256": hashlib.sha256(csr.encode()).hexdigest(),
            "manager_signed_certificate_sha256": hashlib.sha256(
                certificate.encode()).hexdigest(),
            "manager_certificate_install_attempted": True,
            "manager_certificate_install_attempted_at": _now()})
        write_control_state(context.control_state_path, state)
        activity_id = api.install_signed_certificate(certificate)
        if activity_id:
            record["manager_certificate_activity_id"] = activity_id
            write_control_state(context.control_state_path, state)
        _wait_activity(api, activity_id, "Manager certificate")
    deadline = time.monotonic() + 900
    while True:
        inventory = control_component_record(
            api, device_ip=device_ip, personality="vmanage")
        if certificate_is_installed(inventory, root_hash=root_hash):
            break
        if time.monotonic() >= deadline:
            raise RuntimeError("Manager certificate read-back timed out")
        time.sleep(15)
    record.update({"manager_control_certificate": "installed",
                   "manager_root_hash": root_hash})
    write_control_state(context.control_state_path, state)
    return True


def _find_control_record(api, *, personality, addresses, record_uuid=None):
    matches = []
    for record in api.inventory("/dataservice/certificate/record"):
        kinds = {str(record.get("personality", "")).lower(),
                 str(record.get("deviceType", "")).lower()}
        if personality not in kinds:
            continue
        if record_uuid is not None:
            if str(record.get("uuid", "")) == record_uuid:
                matches.append(record)
        elif str(record.get("deviceIP", "")) in addresses:
            matches.append(record)
    if len(matches) > 1:
        raise RuntimeError("Manager contains duplicate " + personality + " records")
    return matches[0] if matches else None


def _enroll_control_component(context, api, name, personality):
    state = read_control_state(context.control_state_path)
    node = state["nodes"][name]
    desired = context.control_plan(name)["desired"]
    device_ip = str(ip_interface(desired["vpn0_address"]).ip)
    system_ip = desired["system_ip"]
    manager_record = control_component_record(
        api, device_ip=context.control_plan("MANAGER1")["desired"]["system_ip"],
        personality="vmanage")
    root_hash = str(manager_record.get("rootCertHash", "")).strip().lower()
    if not certificate_is_installed(manager_record, root_hash=root_hash):
        raise RuntimeError("Manager control certificate prerequisite failed")
    record = _find_control_record(
        api, personality=personality, addresses={device_ip, system_ip},
        record_uuid=node.get("manager_control_uuid"))
    if record is None and node.get("manager_add_attempted"):
        deadline = time.monotonic() + 300
        while record is None and time.monotonic() < deadline:
            time.sleep(15)
            record = _find_control_record(
                api, personality=personality, addresses={device_ip, system_ip})
        if record is None:
            raise RuntimeError(name + " Add was attempted but no record appeared; replay refused")
    if record is None:
        node.update({"manager_add_attempted": True,
                     "manager_add_attempted_at": _now(),
                     "manager_add_device_ip": device_ip})
        write_control_state(context.control_state_path, state)
        response = api.add_control_component(
            device_ip=device_ip, username=os.environ["CISCO_USERNAME"],
            password=os.environ["CISCO_PASSWORD"], personality=personality,
            generate_csr=True,
            **({"protocol": "DTLS", "port": None}
               if personality == "vsmart" else {}))
        if isinstance(response.get("id"), str):
            node["manager_add_activity_id"] = response["id"]
        node["manager_add_result"] = "accepted"
        write_control_state(context.control_state_path, state)
        deadline = time.monotonic() + 300
        while record is None and time.monotonic() < deadline:
            time.sleep(10)
            record = _find_control_record(
                api, personality=personality, addresses={device_ip, system_ip})
        if record is None:
            raise RuntimeError(name + " record did not appear after Add")
    record_uuid = str(record.get("uuid", ""))
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", record_uuid):
        raise RuntimeError(name + " Manager record UUID is unavailable")
    expected_uuid = node.get("manager_control_uuid")
    if expected_uuid is not None and expected_uuid != record_uuid:
        raise RuntimeError(name + " Manager record UUID changed")
    node["manager_control_uuid"] = record_uuid
    write_control_state(context.control_state_path, state)
    if certificate_is_installed(record, root_hash=root_hash):
        node["manager_control_certificate"] = "installed"
        write_control_state(context.control_state_path, state)
        return False
    if node.get("manager_certificate_install_attempted"):
        _wait_activity(api, node.get("manager_certificate_activity_id"),
                       name + " certificate")
    else:
        settled = wait_for_control_component_csr(
            api, record_uuid=record_uuid, personality=personality,
            timeout=900, poll_seconds=15,
            require_lifecycle_complete=personality == "vsmart")
        certificate = _sign_on_manager(
            context, settled.csr,
            "validator-control" if personality == "vbond" else "controller-control")
        node.update({
            "manager_csr_sha256": settled.sha256,
            "manager_signed_certificate_sha256": hashlib.sha256(
                certificate.encode()).hexdigest(),
            "manager_certificate_install_attempted": True,
            "manager_certificate_install_attempted_at": _now()})
        write_control_state(context.control_state_path, state)
        activity_id = api.install_signed_certificate(certificate)
        if activity_id:
            node["manager_certificate_activity_id"] = activity_id
            write_control_state(context.control_state_path, state)
        _wait_activity(api, activity_id, name + " certificate")
    deadline = time.monotonic() + 900
    while True:
        record = control_component_record_by_uuid(
            api, record_uuid=record_uuid, personality=personality)
        if certificate_is_installed(record, root_hash=root_hash):
            break
        if time.monotonic() >= deadline:
            raise RuntimeError(name + " certificate read-back timed out")
        time.sleep(15)
    node.update({"manager_control_certificate": "installed",
                 "manager_root_hash": root_hash})
    write_control_state(context.control_state_path, state)
    return True


def _manager_root(context):
    path = context.root / ".state" / (context.lab + "-enterprise-root.pem")
    certificate = path.read_text()
    certificate_sha256(certificate)
    return certificate


def _ensure_underlay(context, timeout):
    for name in _UNDERLAY:
        _reauth(context)
        lifecycle(context.client, context.topology, "start", node_name=name)
        result = initialize(context.client, context.topology, context.root,
                            context.server_name, name, False, timeout, None)
        if result["failed"] or name not in result["completed"]:
            raise RuntimeError(name + " underlay initialization failed")


def _initialize_control_until_ready(context, name, timeout):
    """Reconnect through transient appliance boot/login churn."""
    deadline = time.monotonic() + timeout
    last_error = None
    while True:
        try:
            return initialize_control(
                context.client, context.topology, context.root,
                context.server_name, name, False, timeout)
        except RuntimeError as error:
            last_error = error
        if time.monotonic() >= deadline:
            raise RuntimeError(
                name + " initialization did not converge before timeout") from last_error
        time.sleep(min(30, max(1, deadline - time.monotonic())))


def _role_up(output, role):
    return bool(re.search(role + r".*\bup\b|\bup\b.*" + role, output, re.I))


def _validate_control_plane(context, api):
    records = api.inventory("/dataservice/system/device/controllers")
    expected = {"vmanage": "172.16.1.101", "vbond": "172.16.1.102",
                "vsmart": "172.16.1.103"}
    for personality, system_ip in expected.items():
        matches = [item for item in records
                   if str(item.get("personality", "")).lower() == personality
                   and item.get("system-ip") == system_ip]
        if len(matches) != 1:
            raise RuntimeError("Control inventory correlation failed for " + personality)
        record = matches[0]
        state = str(record.get("deviceState", record.get("state", ""))).upper()
        if str(record.get("validity", "")).lower() != "valid" or state != "READY":
            raise RuntimeError(personality + " is not READY/valid")
    with _pinned_management_console(context, "CONTROLLER1") as console:
        controller = console.command("show control connections | nomore", timeout=120)
    with _pinned_management_console(context, "VALIDATOR1") as console:
        validator = console.command("show orchestrator connections | nomore", timeout=120)
    with _pinned_management_console(context, "MANAGER1") as console:
        manager = console.command("show control connections | nomore", timeout=120)
    if not (_role_up(controller, "vbond") and _role_up(controller, "vmanage")
            and _role_up(validator, "vsmart")
            and _role_up(manager, "vbond") and _role_up(manager, "vsmart")):
        raise RuntimeError("Controller fabric relationships are not all UP")


def _ensure_control_plane(context, timeout):
    for name in _CONTROL:
        _reauth(context)
        lifecycle(context.client, context.topology, "start", node_name=name)
        _initialize_control_until_ready(context, name, timeout)
    _reauth(context)
    qualify_manager(context.client, context.topology, context.root,
                    context.server_name, "MANAGER1",
                    timeout=max(timeout, 3600), minimum_uptime=900,
                    poll_seconds=15, restart_disabled=True)
    _reauth(context)
    ensure_manager_ca_live(context.client, context.topology, context.root,
                           context.server_name, "MANAGER1", timeout=timeout)
    root = _manager_root(context)
    api = _manager_api(context)
    ensure_fabric_settings(
        api,
        organization=context.control_plan("MANAGER1")["desired"]["organization_name"],
        vbond=str(ip_interface(context.control_plan("VALIDATOR1")
                               ["desired"]["vpn0_address"]).ip),
        root_certificate=root, port=12346)
    _install_manager_certificate(context, api)
    for name, personality in (("VALIDATOR1", "vbond"),
                              ("CONTROLLER1", "vsmart")):
        _install_control_root(context, name, root)
        _enroll_control_component(context, api, name, personality)
    _validate_control_plane(context, api)
    return api


def _edge_state(context, name):
    return context.generation.setdefault("edges", {}).setdefault(name, {})


def _ensure_payg(context, api, name):
    edge = _edge_state(context, name)

    def records():
        return api.inventory("/dataservice/system/device/vedges")

    if edge.get("correlated_uuid"):
        matches = [item for item in records()
                   if str(item.get("uuid", "")).strip()
                   == edge["correlated_uuid"]]
        if len(matches) != 1:
            raise RuntimeError(name + " correlated PAYG identity disappeared")
        return edge, matches[0]
    current = records()
    current_uuids = sorted(str(item.get("uuid", "")).strip()
                           for item in current
                           if str(item.get("uuid", "")).strip())
    if "pre_uuids" not in edge:
        edge["pre_uuids"] = current_uuids
        context.ledger.save()
    elif edge["pre_uuids"] != current_uuids and not edge.get("generation_attempted"):
        raise RuntimeError("WAN-edge inventory changed after durable pre-snapshot")
    if not edge.get("generation_attempted"):
        edge.update({"generation_attempted": True,
                     "generation_attempted_at": _now()})
        context.ledger.save()
        response = api.generate_payg(
            count=1, validity="valid",
            organization=context.control_plan("MANAGER1")["desired"]
            ["organization_name"])
        if isinstance(response.get("id"), str):
            edge["generation_activity_id"] = response["id"]
        edge["generation_result"] = "accepted"
        context.ledger.save()
    deadline = time.monotonic() + 300
    before = [{"uuid": value} for value in edge["pre_uuids"]]
    while True:
        after = records()
        try:
            uuid, record = correlate_single_new(before, after)
            break
        except RuntimeError:
            if time.monotonic() >= deadline:
                raise RuntimeError(name + " PAYG identity did not correlate before timeout")
            time.sleep(5)
    chassis = (record.get("chasisNumber") or record.get("chassisNumber")
               or record.get("chassis-number") or uuid)
    token = record.get("token") or record.get("otp") or record.get("serialNumber")
    if not isinstance(token, str) or not token.strip():
        raise RuntimeError(name + " PAYG record contains no activation token")
    edge.update({"correlated_uuid": uuid, "chassis": chassis,
                 "token": token, "token_present": True})
    context.ledger.save()
    return edge, record


def _transition_edge(context, name, edge, timeout):
    login = credentials(context.root)
    with _eve_console(context, name, Console, timeout) as console:
        console.login(*login)
        version = console.command(
            "show version | include operating mode|System image file", timeout=120)
        if re.search(r"Controller-Managed", version, re.I):
            edge["controller_mode_result"] = "controller-managed-proven"
            context.ledger.save()
            return
        if "Router operating mode: Autonomous" not in version:
            raise RuntimeError(name + " operating mode is unclassified")
        if edge.get("controller_mode_attempted"):
            raise RuntimeError(name + " controller-mode was attempted but did not converge")
        edge.update({"controller_mode_attempted": True,
                     "controller_mode_attempted_at": _now()})
        context.ledger.save()
        console.send("controller-mode enable")
        confirmed = False
        pattern = (
            r"(?i)Continue\?\s*\[confirm\]\s*$|"
            r"Do you want to abort\?[^\n]*:\s*$|"
            r"Proceed[^\n]*\[confirm\]\s*$|"
            r"(?:reload|reboot)[^\n]*(?:\[confirm\]|\[y/n\])[^\n]*$|"
            r"System Bootstrap|Initializing Hardware|Press RETURN to get started|"
            r"^[A-Za-z0-9_.-]+#\s*$")
        for _ in range(10):
            try:
                output, match = console.expect(
                    pattern, timeout=300, latest=True, return_on_timeout=True)
            except RuntimeError as error:
                if confirmed and "ended" in str(error).lower():
                    break
                raise
            if re.search(r"(?im)^%\s*(?:Invalid input|Incomplete command|Ambiguous command)", output):
                raise RuntimeError(name + " rejected controller-mode transition")
            if match is None:
                if confirmed:
                    break
                raise RuntimeError(name + " mode transition produced no confirmation")
            prompt = match.group().strip()
            if re.match(r"Continue\?|Proceed|(?:reload|reboot)", prompt, re.I):
                console.send("")
                confirmed = True
            elif re.match(r"Do you want to abort", prompt, re.I):
                console.send("no")
                confirmed = True
            elif re.search(r"System Bootstrap|Initializing Hardware|Press RETURN", prompt, re.I):
                break
        if not confirmed:
            raise RuntimeError(name + " controller-mode confirmation was not submitted")
    edge["controller_mode_result"] = "reboot-observed"
    context.ledger.save()


def _configure_edge(context, name, edge, timeout):
    login = credentials(context.root)
    stages = stages_from_edge_plan(context.compiled["node_operations"][name])
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        factory_login = False
        try:
            with _eve_console(context, name, CedgeConsole, timeout) as console:
                try:
                    console.login(*login)
                except RuntimeError:
                    if edge.get("post_mode_factory_login_attempted"):
                        raise
                    if login[0].lower() != "admin":
                        raise RuntimeError("Configured Cisco user is not factory admin")
                    edge["post_mode_factory_login_attempted"] = True
                    context.ledger.save()
                    factory_login = True
                if not factory_login:
                    version = console.command(
                        "show version | include operating mode", timeout=120)
                    if not re.search(r"Controller-Managed", version, re.I):
                        raise RuntimeError(name + " is not Controller-Managed")
                    console.command("terminal length 0")
                    for stage in stages:
                        before = console.command("show sdwan running-config", timeout=180)
                        if missing_desired_commands(before, (stage,)):
                            console.configure_stage(stage, timeout=120)
                            after = console.command("show sdwan running-config", timeout=180)
                            if missing_desired_commands(after, (stage,)):
                                raise RuntimeError(
                                    name + " stage read-back incomplete: " + stage.name)
                    running = console.command("show sdwan running-config", timeout=180)
                    if missing_desired_commands(running, stages):
                        raise RuntimeError(name + " desired-state read-back is incomplete")
                    edge["baseline_complete"] = True
                    context.ledger.save()
                    return
        except RuntimeError as error:
            last_error = error
        if factory_login:
            with _eve_console(context, name, CedgeConsole, timeout) as console:
                console.login("admin", "admin", login[2], new_password=login[1])
            edge["post_mode_factory_login_result"] = "password-initialized"
            context.ledger.save()
        else:
            time.sleep(15)
    raise RuntimeError(name + " did not reach configurable controller mode") from last_error


def _manager_ssh_fingerprints(context):
    with _pinned_management_console(context, "MANAGER1") as console:
        vpn0 = console.command(
            "show running-config vpn 0 interface eth1 | nomore", timeout=120)
        if ("tunnel-interface" not in vpn0
                or not re.search(r"allow-service\s+(?:all|ssh|sshd)", vpn0)):
            raise RuntimeError("Manager VPN0 SSH service exposure is not proven")
        root = manager_ca_certificate(console)
        _enter_shell(console)
        status, output = _shell_command(
            console,
            "for f in /etc/ssh/ssh_host_*_key.pub; do test -s \"$f\" && "
            "ssh-keygen -lf \"$f\" -E sha256; done")
        _leave_shell(console)
    fingerprints = set(re.findall(r"SHA256:[A-Za-z0-9+/]+", output))
    if status != "0" or not fingerprints:
        raise RuntimeError("Manager SSH host fingerprints are unavailable")
    return root, fingerprints


def _complete_edge(context, api, name, edge, timeout):
    uuid, chassis, token = (edge.get("correlated_uuid"), edge.get("chassis"),
                            edge.get("token"))
    if not all(isinstance(value, str) and value for value in (uuid, chassis, token)):
        raise RuntimeError(name + " correlated PAYG material is incomplete")
    login = credentials(context.root)
    source_pem, fingerprints = _manager_ssh_fingerprints(context)
    source_hash = certificate_sha256(source_pem)
    with _eve_console(context, name, CedgeConsole, timeout) as console:
        console.login(*login, read_only=True)
        route = console.command("show ip route 10.1.0.0 255.255.255.0", timeout=120)
        next_hops = sorted(set(re.findall(r"10\.65\.(?:91|92)\.100", route)))
        if next_hops != ["10.65.91.100", "10.65.92.100"]:
            raise RuntimeError(name + " lacks both controller next hops")
        for address in ("10.1.0.1", "10.1.0.2", "10.1.0.3"):
            ping = console.command("ping " + address + " repeat 5 timeout 1", timeout=60)
            if not re.search(r"Success rate is 100 percent \(5/5\)", ping):
                raise RuntimeError(name + " cannot reach controller " + address)
        root = console.command("show sdwan certificate root-ca-cert", timeout=120)
        if "nwl-lab-sdwan-CA" not in root:
            try:
                destination_pem, size = console.read_certificate_file(
                    "bootflash:SDWAN.pem")
                copied = certificate_sha256(destination_pem) == source_hash
            except RuntimeError:
                copied = False
            if not copied:
                console.copy_scp_absolute(
                    login[0], "10.1.0.1", "/home/admin/SDWAN.pem",
                    "bootflash:SDWAN.pem", login[1], fingerprints, timeout=120)
                destination_pem, size = console.read_certificate_file(
                    "bootflash:SDWAN.pem")
            if size <= 0 or certificate_sha256(destination_pem) != source_hash:
                raise RuntimeError("Transferred Manager CA failed source validation")
            console.install_root(
                "bootflash:SDWAN.pem", "nwl-lab-sdwan-CA", timeout=180)
        records = [item for item in api.inventory("/dataservice/system/device/vedges")
                   if str(item.get("uuid", "")).strip() == uuid]
        if len(records) != 1:
            raise RuntimeError(name + " Manager PAYG correlation failed")
        record = records[0]
        manager_chassis = record.get("chasisNumber") or record.get("chassisNumber")
        if manager_chassis != chassis:
            raise RuntimeError(name + " Manager PAYG chassis changed")
        local = console.command("show sdwan control local-properties", timeout=120)
        active = (chassis in local and bool(re.search(
            r"^certificate-status\s+Installed\s*$", local, re.I | re.M)))
        lifecycle_state = record.get("vedgeCertificateState") or record.get("certificateState")
        if not active:
            if edge.get("activation_attempted"):
                pass  # Never replay; wait below for the prior attempt to converge.
            elif lifecycle_state == "tokengenerated":
                edge.update({"activation_attempted": True,
                             "activation_attempted_at": _now(),
                             "activation_uuid": uuid})
                context.ledger.save()
                console.activate_payg(
                    chassis, token, lambda: None, timeout=min(timeout, 600))
                edge["activation_result"] = "command-returned"
                context.ledger.save()
            else:
                raise RuntimeError(name + " PAYG activation is not safely pending")
        deadline = time.monotonic() + 900
        while True:
            local = console.command("show sdwan control local-properties", timeout=120)
            connections = console.command("show sdwan control connections", timeout=120)
            omp = console.command("show sdwan omp peers", timeout=120)
            records = [item for item in api.inventory("/dataservice/system/device/vedges")
                       if str(item.get("uuid", "")).strip() == uuid]
            roles = {role: _role_up(connections, role)
                     for role in ("vbond", "vmanage", "vsmart")}
            device_ready = (chassis in local
                            and bool(re.search(r"^root-ca-chain-status\s+Installed\s*$", local, re.I | re.M))
                            and bool(re.search(r"^certificate-status\s+Installed\s*$", local, re.I | re.M)))
            manager_ready = (len(records) == 1
                             and (records[0].get("vedgeCertificateState")
                                  or records[0].get("certificateState")) == "certinstalled"
                             and records[0].get("validity") == "valid")
            omp_up = bool(re.search(
                r"172\.16\.1\.103.*\bup\b|\bup\b.*172\.16\.1\.103", omp, re.I))
            if device_ready and manager_ready and all(roles.values()) and omp_up:
                edge.update({"accepted": True, "accepted_at": _now()})
                context.ledger.save()
                return
            if time.monotonic() >= deadline:
                raise RuntimeError(name + " did not reach edge control acceptance")
            time.sleep(15)


def _validator_authorized(context, uuids):
    with _pinned_management_console(context, "VALIDATOR1") as console:
        output = console.command("show orchestrator valid-vedges | nomore", timeout=120)
    normalized = "".join(output.split()).lower()
    if any(uuid.lower() not in normalized for uuid in uuids):
        raise RuntimeError("Validator valid-edge ledger omitted correlated identities")


def _validate_edges(context, api):
    login = credentials(context.root)
    system_ips = {"CEDGE-S2": "172.16.1.1", "CEDGE-S3": "172.16.1.3",
                  "CEDGE-S4": "172.16.1.4"}
    records = {str(item.get("uuid", "")).strip(): item
               for item in api.inventory("/dataservice/system/device/vedges")}
    uuids, result = [], {}
    for name in _EDGES:
        edge = _edge_state(context, name)
        uuid = edge.get("correlated_uuid")
        uuids.append(uuid)
        stages = stages_from_edge_plan(context.compiled["node_operations"][name])
        with _eve_console(context, name, Console, 300) as console:
            console.login(*login)
            console.command("terminal length 0")
            running = console.command("show sdwan running-config", timeout=180)
            local = console.command("show sdwan control local-properties", timeout=120)
            control = console.command("show sdwan control connections", timeout=120)
            omp = console.command("show sdwan omp peers", timeout=120)
            bfd = console.command("show sdwan bfd sessions", timeout=120)
        missing = missing_desired_commands(running, stages)
        peer_ips = [value for peer, value in system_ips.items() if peer != name]
        bfd_peers = {address: len(re.findall(
            r"(?im)^.*" + re.escape(address) + r".*\bup\b.*$", bfd))
            for address in peer_ips}
        record = records.get(uuid, {})
        accepted = (not missing and uuid in local
                    and bool(re.search(r"^root-ca-chain-status\s+Installed\s*$", local, re.I | re.M))
                    and bool(re.search(r"^certificate-status\s+Installed\s*$", local, re.I | re.M))
                    and all(_role_up(control, role)
                            for role in ("vbond", "vmanage", "vsmart"))
                    and bool(re.search(r"172\.16\.1\.103.*\bup\b|\bup\b.*172\.16\.1\.103", omp, re.I))
                    and all(count >= 2 for count in bfd_peers.values())
                    and (record.get("vedgeCertificateState")
                         or record.get("certificateState")) == "certinstalled"
                    and record.get("deviceState") == "READY"
                    and record.get("validity") == "valid")
        result[name] = {"accepted": accepted, "missing_count": len(missing),
                        "bfd_up_sessions": bfd_peers}
    _validator_authorized(context, uuids)
    if not all(item["accepted"] for item in result.values()):
        raise RuntimeError("Three-edge acceptance failed")
    return result


def run_factory(client, topology, root, server_name="default", *,
                destroy_first=False, timeout=1200):
    """Build the declared lab to full fabric-ready state, resuming safely."""
    if not 300 <= timeout <= 7200:
        raise ValueError("Factory timeout must be between 300 and 7200 seconds")
    _required_environment()
    root = Path(root)
    declared = load_topology(root, topology["name"])
    preflight(root, topology["name"], declared)
    if destroy_first:
        delete(client, topology)
    apply_result = apply(client, declared, prune=True)
    nodes = named(client, lab_path(declared) + "/nodes")
    ledger = FactoryLedger(root / ".state" / (
        topology["name"] + "-factory-state.json"))
    generation = ledger.bind(nodes)
    context = FactoryContext(
        client, declared, root, server_name,
        load_and_compile(root, topology["name"], declared), nodes,
        ledger, generation)
    _ensure_underlay(context, timeout)
    api = _ensure_control_plane(context, timeout)
    for name in _EDGES:
        edge, _ = _ensure_payg(context, api, name)
        _reauth(context)
        lifecycle(client, declared, "start", node_name=name)
        _transition_edge(context, name, edge, timeout)
        _configure_edge(context, name, edge, timeout)
        _complete_edge(context, api, name, edge, timeout)
    edges = _validate_edges(context, api)
    generation.update({"factory_ready": True, "factory_ready_at": _now()})
    ledger.save()
    return {"lab": topology["name"],
            "generation": ledger.value["active_generation"],
            "apply": {"changed": bool(apply_result.get("changes")),
                      "direct_links": apply_result["presentation"]["direct_links"],
                      "backing_networks_hidden": apply_result["presentation"]
                      ["backing_networks_hidden"]},
            "control_plane": "ready", "edges": edges,
            "result": "CATALYST_SDWAN_FABRIC_READY"}
