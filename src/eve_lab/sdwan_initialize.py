"""Initialize one Catalyst SD-WAN control component from compiled intent."""
import argparse
import hashlib
from ipaddress import ip_interface
import json
import os
from pathlib import Path
import re
import socket
import sys
from urllib.parse import urlsplit

import paramiko

from .client import EveClient
from .config import load_server
from .deploy import lab_path, named
from .device_console import credentials
from .initialize import _open_telnet_console, telnet_console_url
from .live_guard import enforce_live_guard
from .sdwan_control import ViptelaConsole, stages_from_plan
from .sdwan_intent import load_and_compile
from .sdwan_pki import ensure_manager_ca, manager_ca_certificate
from .sdwan_readiness import (
    parse_all_nms_status, parse_application_status,
    wait_for_application_server,
)
from .topology import load_lab_target, load_topology


class DesiredStateMissing(RuntimeError):
    """The device was read successfully but lacks declared configuration."""


def _state_path(root, lab):
    return Path(root) / ".state" / (lab + "-control-state.json")


def _read_state(path):
    if not path.exists():
        return {"version": 1, "nodes": {}}
    value = json.loads(path.read_text())
    if (not isinstance(value, dict) or value.get("version") != 1
            or not isinstance(value.get("nodes"), dict)):
        raise ValueError("Invalid control initialization state")
    return value


def _write_state(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def _first_login(console, login, state, path, node_name, node_uuid, *, manager=False):
    record = state["nodes"].get(node_name)
    fresh = not isinstance(record, dict) or record.get("eve_uuid") != node_uuid
    logged_in = False
    if fresh:
        record = {"eve_uuid": node_uuid, "first_login": "pending",
                  "completed_stages": []}
        def persist_pending():
            state["nodes"][node_name] = record
            _write_state(path, state)
        try:
            console.login("admin", "admin", login[2], new_password=login[1],
                          on_password_submit=persist_pending,
                          vmanage_first_boot=manager)
        except RuntimeError:
            # Recovery is safe only after the hook durably proves the factory
            # password was submitted for this exact EVE node UUID.
            if (not manager
                    or state["nodes"].get(node_name) is not record):
                raise
            print(
                "Manager first-boot session crossed the correlated password "
                "boundary; continuing with configured credentials...",
                file=sys.stderr, flush=True)
        else:
            state["nodes"][node_name] = record
            logged_in = True
    version = None
    for attempt in range(6 if manager else 1):
        if not logged_in:
            try:
                console.login(
                    login[0], login[1], login[2], new_password=login[1],
                    vmanage_first_boot=manager)
            except RuntimeError:
                if not manager or attempt == 5:
                    raise
                print(
                    "Manager login was transient during first boot; waiting "
                    "for the next configured post-reboot login...",
                    file=sys.stderr, flush=True)
                continue
            logged_in = True
        try:
            version = console.command("show version", timeout=60)
        except RuntimeError:
            if not manager or attempt == 5:
                raise
            logged_in = False
            print(
                "Manager CLI was transient during first boot; waiting for the "
                "configured post-reboot login...", file=sys.stderr, flush=True)
            continue
        break
    if version is None or "20.15.1" not in version:
        raise RuntimeError("Control component version read-back did not prove 20.15.1")
    print("Control-component version 20.15.1 read-back passed.",
          file=sys.stderr, flush=True)
    record["first_login"] = "complete"
    _write_state(path, state)
    return record


def _stage_command(name):
    return {
        "identity": "show running-config system | nomore",
        "vpn0": "show running-config vpn 0 | nomore",
        "vpn512": "show running-config vpn 512 | nomore",
    }[name]


def _expected_lines(stage):
    ignored = {"system", "vpn 0", "vpn 512", "exit", "no shutdown"}
    return [command for command in stage.commands if command not in ignored
            and not command.startswith("no interface ")]


def _normalize_line(line):
    collapsed = re.sub(r"\s+", " ", line.strip())
    return re.sub(r'"([^"\s]+)"', r"\1", collapsed)


def verify_stage(console, stage, *, timeout=60):
    output = console.command(_stage_command(stage.name), timeout=timeout)
    normalized = {_normalize_line(line)
                  for line in output.splitlines() if line.strip()}
    expected = _expected_lines(stage)
    missing = [index for index, line in enumerate(expected, start=1)
               if _normalize_line(line) not in normalized]
    if missing and stage.name == "identity":
        detailed = console.command(
            "show running-config system | details | nomore", timeout=timeout)
        normalized.update(
            _normalize_line(line) for line in detailed.splitlines()
            if line.strip())
        missing = [index for index, line in enumerate(expected, start=1)
                   if _normalize_line(line) not in normalized]
    if missing:
        raise DesiredStateMissing(
            "Control-component " + stage.name +
            " read-back is missing desired state at line indexes " +
            ",".join(str(index) for index in missing))
    return {"stage": stage.name, "desired_lines": len(expected),
            "missing": 0}


def ensure_stage(console, stage, *, timeout=300, on_apply=None):
    """Read back a stage first and mutate only confirmed missing state."""
    try:
        return verify_stage(console, stage, timeout=timeout), False
    except DesiredStateMissing:
        if on_apply is not None:
            on_apply()
        console.configure_stage(stage, timeout=timeout)
        return verify_stage(console, stage, timeout=timeout), True


def initialize_control(client, topology, root, server_name, node_name,
                       check=False, timeout=900):
    if not 1 <= timeout <= 3600:
        raise ValueError("timeout must be between 1 and 3600 seconds")
    declared = load_topology(Path(root), topology["name"])
    plan = load_and_compile(Path(root), topology["name"], declared)[
        "node_operations"].get(node_name)
    stages = stages_from_plan(plan)
    nodes = named(client, lab_path(topology) + "/nodes")
    if node_name not in nodes:
        raise ValueError("Control component not found: " + node_name)
    node = nodes[node_name]
    if str(node.get("status")) != "2":
        raise RuntimeError("Start " + node_name + " before initialization")
    url = telnet_console_url(node)
    if url is None:
        raise RuntimeError("Control component lacks a native Telnet console")
    if check:
        return {"lab": topology["name"], "node": node_name, "check": True,
                "console_port": url.port,
                "stages": [stage.name for stage in stages]}

    login = credentials(Path(root))
    server = load_server(Path(root), server_name, auth="ssh")
    ssh = paramiko.SSHClient()
    channel = None
    try:
        ssh.load_system_host_keys()
        ssh.connect(server.get("ssh_host") or urlsplit(server["url"]).hostname,
                    username=server["ssh_username"], password=server["ssh_password"],
                    timeout=10, auth_timeout=10, banner_timeout=10,
                    allow_agent=False, look_for_keys=False)
        channel = _open_telnet_console(ssh, url.port)
        console = ViptelaConsole(channel, boot_timeout=timeout)
        path = _state_path(root, topology["name"])
        state = _read_state(path)
        record = _first_login(
            console, login, state, path, node_name, str(node.get("uuid", "")),
            manager=plan.get("personality") == "manager")
        evidence = []
        for stage in stages:
            print("Reading control-component " + stage.name + " stage...",
                  file=sys.stderr, flush=True)
            completed = record.setdefault("completed_stages", [])
            attempted = record.setdefault("attempted_stages", [])
            if stage.name in completed or stage.name in attempted:
                result = verify_stage(
                    console, stage, timeout=min(timeout, 300))
                changed = False
            else:
                def persist_attempt():
                    attempted.append(stage.name)
                    _write_state(path, state)
                result, changed = ensure_stage(
                    console, stage, timeout=min(timeout, 300),
                    on_apply=persist_attempt)
            if changed:
                print("Control-component " + stage.name +
                      " missing state was committed.",
                      file=sys.stderr, flush=True)
            else:
                print("Control-component " + stage.name +
                      " already matched desired state.",
                      file=sys.stderr, flush=True)
            evidence.append(result)
            print("Control-component " + stage.name + " read-back passed.",
                  file=sys.stderr, flush=True)
            if stage.name not in completed:
                completed.append(stage.name)
                _write_state(path, state)
        return {"lab": topology["name"], "node": node_name,
                "first_login": record["first_login"],
                "version": "20.15.1", "stages": evidence}
    finally:
        if channel is not None:
            channel.close()
        ssh.close()


def _ensure_manager_application_enabled(
        console, output, record, state, path, *, restart_disabled, timeout):
    status = parse_application_status(output)
    if status.enabled:
        return False
    if not restart_disabled:
        raise RuntimeError(
            "Manager application server is disabled; restart was not authorized")
    if record.get("nms_restart_attempted"):
        raise RuntimeError(
            "Manager NMS restart was already submitted for this EVE node UUID")
    record["nms_restart_attempted"] = True
    _write_state(path, state)
    console.command("request nms all restart", timeout=min(timeout, 900))
    return True


def qualify_manager(client, topology, root, server_name, node_name, *,
                    timeout=3600, minimum_uptime=900, poll_seconds=12,
                    restart_disabled=False):
    """Prove a configured Manager application process is stable over its CLI."""
    declared = load_topology(Path(root), topology["name"])
    plan = load_and_compile(Path(root), topology["name"], declared)[
        "node_operations"].get(node_name)
    if (not isinstance(plan, dict)
            or plan.get("adapter") != "viptela-control"
            or plan.get("personality") != "manager"):
        raise ValueError(node_name + " is not the declared Manager")
    nodes = named(client, lab_path(topology) + "/nodes")
    if node_name not in nodes:
        raise ValueError("Manager not found: " + node_name)
    node = nodes[node_name]
    if str(node.get("status")) != "2":
        raise RuntimeError("Start " + node_name + " before qualification")
    state_path = _state_path(root, topology["name"])
    state = _read_state(state_path)
    record = state["nodes"].get(node_name)
    if (not isinstance(record, dict)
            or record.get("eve_uuid") != str(node.get("uuid", ""))
            or record.get("first_login") != "complete"
            or set(record.get("completed_stages", ()))
            != {"identity", "vpn0", "vpn512"}):
        raise RuntimeError(
            "Manager initialization correlation is incomplete; qualification refused")
    url = telnet_console_url(node)
    if url is None:
        raise RuntimeError("Manager lacks a native Telnet console")

    login = credentials(Path(root))
    server = load_server(Path(root), server_name, auth="ssh")
    ssh = paramiko.SSHClient()
    channel = None
    try:
        ssh.load_system_host_keys()
        ssh.connect(server.get("ssh_host") or urlsplit(server["url"]).hostname,
                    username=server["ssh_username"], password=server["ssh_password"],
                    timeout=10, auth_timeout=10, banner_timeout=10,
                    allow_agent=False, look_for_keys=False)
        channel = _open_telnet_console(ssh, url.port)
        console = ViptelaConsole(channel, boot_timeout=min(timeout, 900))
        console.login(login[0], login[1], login[2])
        version = console.command("show version", timeout=60)
        if "20.15.1" not in version:
            raise RuntimeError("Manager version read-back did not prove 20.15.1")
        initial_status = console.command(
            "request nms application-server status", timeout=60)
        restarted = _ensure_manager_application_enabled(
            console, initial_status, record, state, state_path,
            restart_disabled=restart_disabled, timeout=timeout)
        pending_status = [] if restarted else [initial_status]
        def report_wait(reason, pid, uptime):
            fields = [reason]
            if pid is not None:
                fields.append("PID=" + str(pid))
            if uptime is not None:
                fields.append("uptime=" + str(uptime) + "s")
            print("Manager application readiness: " + ", ".join(fields),
                  file=sys.stderr, flush=True)
        def read_status():
            if pending_status:
                return pending_status.pop()
            return console.command(
                "request nms application-server status", timeout=60)
        observation = wait_for_application_server(
            read_status,
            timeout_seconds=timeout, poll_seconds=poll_seconds,
            minimum_seconds=minimum_uptime, on_wait=report_wait)
        return {"lab": topology["name"], "node": node_name,
                "version": "20.15.1", "qualified": observation.qualified,
                "pid": observation.pid,
                "uptime_seconds": observation.uptime_seconds,
                "minimum_uptime_seconds": minimum_uptime}
    finally:
        if channel is not None:
            channel.close()
        ssh.close()


def inspect_manager_services(client, topology, root, server_name, node_name,
                             *, timeout=900):
    """Return a secret-free read-only classification of Manager NMS services."""
    declared = load_topology(Path(root), topology["name"])
    plan = load_and_compile(Path(root), topology["name"], declared)[
        "node_operations"].get(node_name)
    if (not isinstance(plan, dict)
            or plan.get("adapter") != "viptela-control"
            or plan.get("personality") != "manager"):
        raise ValueError(node_name + " is not the declared Manager")
    nodes = named(client, lab_path(topology) + "/nodes")
    if node_name not in nodes or str(nodes[node_name].get("status")) != "2":
        raise RuntimeError("Manager must be running for service inspection")
    url = telnet_console_url(nodes[node_name])
    if url is None:
        raise RuntimeError("Manager lacks a native Telnet console")
    login = credentials(Path(root))
    server = load_server(Path(root), server_name, auth="ssh")
    ssh = paramiko.SSHClient()
    channel = None
    try:
        ssh.load_system_host_keys()
        ssh.connect(server.get("ssh_host") or urlsplit(server["url"]).hostname,
                    username=server["ssh_username"], password=server["ssh_password"],
                    timeout=10, auth_timeout=10, banner_timeout=10,
                    allow_agent=False, look_for_keys=False)
        channel = _open_telnet_console(ssh, url.port)
        console = ViptelaConsole(channel, boot_timeout=timeout)
        console.login(login[0], login[1], login[2])
        services = parse_all_nms_status(console.command(
            "request nms all status | nomore", timeout=min(timeout, 300)))
        return {
            "lab": topology["name"], "node": node_name,
            "services": [
                {"name": item.name, "enabled": item.enabled,
                 "state": item.state, "pid": item.pid,
                 "uptime_seconds": item.uptime_seconds}
                for item in services],
        }
    finally:
        if channel is not None:
            channel.close()
        ssh.close()


def ensure_manager_ca_live(client, topology, root, server_name, node_name,
                           *, timeout=900):
    """Create/read back the Manager-local CA and persist only its public root."""
    declared = load_topology(Path(root), topology["name"])
    plan = load_and_compile(Path(root), topology["name"], declared)[
        "node_operations"].get(node_name)
    if (not isinstance(plan, dict)
            or plan.get("adapter") != "viptela-control"
            or plan.get("personality") != "manager"):
        raise ValueError(node_name + " is not the declared Manager")
    nodes = named(client, lab_path(topology) + "/nodes")
    node = nodes.get(node_name)
    if node is None or str(node.get("status")) != "2":
        raise RuntimeError("Manager must be running for CA initialization")
    state_path = _state_path(root, topology["name"])
    state = _read_state(state_path)
    record = state["nodes"].get(node_name)
    if (not isinstance(record, dict)
            or record.get("eve_uuid") != str(node.get("uuid", ""))
            or set(record.get("completed_stages", ()))
            != {"identity", "vpn0", "vpn512"}):
        raise RuntimeError("Manager baseline is not durably correlated")
    login = credentials(Path(root))
    del server_name
    try:
        address = str(ip_interface(
            declared["management"]["assignments"][node_name]).ip)
    except (KeyError, ValueError) as error:
        raise ValueError(
            "Manager requires one declared VPN512 management address") from error
    sock = socket.create_connection((address, 22), timeout=10)
    transport = paramiko.Transport(sock)
    channel = None
    try:
        transport.start_client(timeout=10)
        fingerprint = hashlib.sha256(
            transport.get_remote_server_key().asbytes()).hexdigest()
        expected = record.get("management_ssh_sha256")
        if expected is not None and expected != fingerprint:
            raise RuntimeError("Manager VPN512 SSH host key changed")
        transport.auth_password(login[0], login[1])
        if expected is None:
            record["management_ssh_sha256"] = fingerprint
            _write_state(state_path, state)
        channel = transport.open_session(timeout=10)
        channel.get_pty()
        channel.invoke_shell()
        console = ViptelaConsole(channel, boot_timeout=min(timeout, 300))
        console.expect(
            r"(?m)^[A-Za-z0-9_.-]+#\s*$", timeout=min(timeout, 300),
            wake=True, latest=True)
        created = ensure_manager_ca(console, declared["organization"])
        certificate = manager_ca_certificate(console)
        fingerprint = hashlib.sha256(certificate.encode("ascii")).hexdigest()
        public_path = Path(root) / ".state" / (
            topology["name"] + "-enterprise-root.pem")
        public_path.write_text(certificate)
        record["enterprise_ca_sha256"] = fingerprint
        _write_state(state_path, state)
        return {"lab": topology["name"], "node": node_name,
                "created": created, "certificate_sha256": fingerprint,
                "public_certificate": str(public_path)}
    finally:
        if channel is not None:
            channel.close()
        transport.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lab")
    parser.add_argument("node")
    parser.add_argument("--root", type=Path,
                        default=Path(__file__).resolve().parents[2])
    parser.add_argument("--server", default="default")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args(argv)
    try:
        topology = load_lab_target(args.root, args.lab)
        web = load_server(args.root, args.server)
        enforce_live_guard(args.root, topology, web)
        client = EveClient(web["url"], web.get("timeout", 15))
        client.login(web["username"], web["password"], html5=False)
        try:
            result = initialize_control(
                client, topology, args.root, args.server, args.node,
                args.check, args.timeout)
        finally:
            client.logout()
        print(json.dumps(result, indent=2))
    except (OSError, ValueError, RuntimeError, paramiko.SSHException) as error:
        parser.exit(1, "Error: " + str(error) + "\n")


if __name__ == "__main__":
    main()

