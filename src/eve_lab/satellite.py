"""Read-only EVE satellite image readiness preflight."""

import base64
import json
import re
import shlex
import time
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlsplit

import paramiko

from .config import load_server


IMAGE_ROOT = "/opt/unetlab/addons/qemu"
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_PUBLIC_KEY = re.compile(r"[A-Za-z0-9+/=]{16,128}\Z")


def _valid_name(value, label):
    if not isinstance(value, str) or not _NAME.fullmatch(value):
        raise ValueError(f"{label} must be an EVE-safe basename")


def _probe_script(image):
    """Return a POSIX shell probe; it does not create, alter, or checksum files."""
    directory = IMAGE_ROOT + "/" + image
    return f'''directory={shlex.quote(directory)}
if [ ! -d "$directory" ]; then
  printf 'STATE|MISSING\\n'
  exit 0
fi
printf 'STATE|PRESENT\\n'
writer=0
if ps -eo args= | grep -E '(^|/)(rsync|scp|cp)( |$)|qemu-img[[:space:]]+(convert|create)' | grep -F -- "$directory" >/dev/null 2>&1; then
  writer=1
fi
printf 'WRITER|%s\\n' "$writer"
found=0
for file in "$directory"/*.qcow2; do
  [ -f "$file" ] || continue
  found=1
  name=${{file##*/}}
  metadata=$(stat -c '%s|%Y' -- "$file") || {{ printf 'FILE_ERROR|%s\\n' "$name"; continue; }}
  printf 'FILE|%s|%s\\n' "$name" "$metadata"
  if details=$(qemu-img info --output=json -- "$file" 2>&1); then
    encoded=$(printf %s "$details" | base64 -w 0)
    printf 'QEMU|%s|%s\\n' "$name" "$encoded"
  else
    encoded=$(printf %s "$details" | base64 -w 0)
    printf 'QEMU_ERROR|%s|%s\\n' "$name" "$encoded"
  fi
done
[ "$found" = 1 ] || printf 'NO_QCOW2\\n'
'''


def remote_command(satellite, image):
    """Build a manager-mediated, read-only SSH command for an EVE satellite."""
    _valid_name(satellite, "Satellite name")
    _valid_name(image, "Image")
    encoded = base64.b64encode(_probe_script(image).encode()).decode()
    remote = "echo " + encoded + " | base64 -d | /bin/sh"
    return ("ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=10 "
            + shlex.quote(satellite) + " " + shlex.quote(remote))


def resolution_command(satellite, public_key=None):
    """Resolve a cluster member over manager SSH without exposing its config."""
    _valid_name(satellite, "Satellite name")
    if public_key is not None and (not isinstance(public_key, str) or not _PUBLIC_KEY.fullmatch(public_key)):
        raise ValueError("Satellite WireGuard public key is invalid")
    key = "" if public_key is None else public_key
    return f'''name={shlex.quote(satellite)}
key={shlex.quote(key)}
target=$(getent ahostsv4 "$name" 2>/dev/null | awk 'NR==1 {{print $1}}')
source=dns
if [ -z "$target" ] && [ -n "$key" ]; then
  target=$(wg show wg0 dump 2>/dev/null | awk -v key="$key" '$1 == key {{split($4, list, ","); split(list[1], cidr, "/"); print cidr[1]; exit}}')
  source=wireguard
fi
printf 'TARGET|%s|%s\n' "$target" "$source"
'''


def _target_from_output(output):
    for line in output.splitlines():
        parts = line.split("|", 2)
        if len(parts) == 3 and parts[0] == "TARGET":
            try:
                ip_address(parts[1])
            except ValueError:
                return None, parts[2]
            return parts[1], parts[2]
    return None, None


def satellite_member(cluster, satellite_id):
    """Return one online non-manager member for an EVE satellite ID."""
    if type(satellite_id) is not int or satellite_id < 1:
        raise ValueError("Satellite console target must be a positive EVE satellite ID")
    candidates = [item for item in cluster.values() if isinstance(item, dict)
                  and item.get("id") == satellite_id]
    if len(candidates) != 1:
        raise RuntimeError(f"Satellite {satellite_id} is not present in EVE cluster inventory")
    member = candidates[0]
    if member.get("name") == "master" or member.get("online") != 1:
        raise RuntimeError(f"Satellite {member.get('name', satellite_id)} is not online")
    _valid_name(member.get("name"), "Satellite name")
    return member


def resolve_satellite_target(manager, member):
    """Resolve one cluster member through an existing verified manager SSH session."""
    stdin, stdout, stderr = manager.exec_command(
        resolution_command(member["name"], member.get("pubkey")), timeout=15)
    stdin.close()
    output = stdout.read().decode(errors="replace")
    error = stderr.read().decode(errors="replace")
    if stdout.channel.recv_exit_status() != 0:
        raise RuntimeError("Selected satellite address discovery failed: " + error[:240])
    target, _ = _target_from_output(output)
    if target is None:
        raise RuntimeError("Configured SSH transport could not resolve selected satellite " + member["name"])
    return target


def console_command(target, port):
    """Build a strict manager-to-satellite command for a local EVE console port."""
    try:
        address = str(ip_address(target))
    except ValueError:
        raise ValueError("Satellite console target must be an IP address") from None
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("Satellite console port must be between 1 and 65535")
    remote = "telnet 127.0.0.1 " + str(port)
    return ("ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=10 "
            + shlex.quote(address) + " " + shlex.quote(remote))

def parse_snapshot(output):
    """Parse deliberately small line-oriented evidence from the read-only probe."""
    snapshot = {"directory": False, "writer": False, "files": [], "errors": []}
    files = {}
    for line in output.splitlines():
        parts = line.split("|", 2)
        tag = parts[0]
        if tag == "STATE" and len(parts) == 2:
            snapshot["directory"] = parts[1] == "PRESENT"
        elif tag == "WRITER" and len(parts) == 2:
            snapshot["writer"] = parts[1] == "1"
        elif tag == "FILE" and len(parts) == 3:
            try:
                name, size, mtime = parts[1], *parts[2].split("|", 1)
                files[name] = {"name": name, "size_bytes": int(size), "mtime_epoch": int(mtime)}
            except (TypeError, ValueError):
                snapshot["errors"].append("Malformed FILE evidence")
        elif tag in ("QEMU", "QEMU_ERROR") and len(parts) == 3:
            name = parts[1]
            try:
                details = base64.b64decode(parts[2], validate=True).decode()
            except (ValueError, UnicodeDecodeError):
                snapshot["errors"].append(f"Malformed qemu-img evidence for {name}")
                continue
            if tag == "QEMU_ERROR":
                snapshot["errors"].append(f"qemu-img rejected {name}: {details[:160]}")
                continue
            try:
                qemu = json.loads(details)
            except json.JSONDecodeError:
                snapshot["errors"].append(f"qemu-img returned invalid JSON for {name}")
                continue
            file = files.setdefault(name, {"name": name})
            file["format"] = qemu.get("format")
            file["virtual_size"] = qemu.get("virtual-size")
        elif tag in ("FILE_ERROR", "NO_QCOW2"):
            snapshot["errors"].append(line)
    snapshot["files"] = [files[name] for name in sorted(files)]
    return snapshot


def _signature(snapshot):
    return tuple((entry.get("name"), entry.get("size_bytes"), entry.get("mtime_epoch"),
                  entry.get("format"), entry.get("virtual_size")) for entry in snapshot["files"])


def assess_image_snapshots(image, expected_disks, snapshots, required_names=None):
    """Classify a bounded set of image snapshots without using checksums."""
    if not snapshots:
        raise ValueError("At least one satellite image snapshot is required")
    evidence = {"image": image, "expected_qcow2_disks": expected_disks,
                "poll_count": len(snapshots), "snapshots": snapshots}
    if any(not snapshot["directory"] for snapshot in snapshots):
        return {**evidence, "status": "MISSING", "reason": "Image directory is absent on the selected satellite"}
    if any(snapshot["errors"] for snapshot in snapshots):
        return {**evidence, "status": "INVALID", "reason": "Image files are unreadable or qemu-img did not recognize them"}
    if required_names is None:
        counts = {len(snapshot["files"]) for snapshot in snapshots}
        if counts != {expected_disks}:
            return {**evidence, "status": "MISSING", "reason": "Expected QCOW2 disk layout is not present"}
    else:
        evidence["required_qcow2_names"] = list(required_names)
        if any(not set(required_names).issubset(
                {entry["name"] for entry in snapshot["files"]}) for snapshot in snapshots):
            return {**evidence, "status": "MISSING", "reason": "Required QCOW2 disks are not present"}
    if any(entry.get("format") != "qcow2" for snapshot in snapshots for entry in snapshot["files"]):
        return {**evidence, "status": "INVALID", "reason": "A .qcow2 file is not recognized as QCOW2"}
    if any(snapshot["writer"] for snapshot in snapshots):
        return {**evidence, "status": "COPYING/UNSTABLE", "reason": "A relevant image-copy process is active"}
    if len({_signature(snapshot) for snapshot in snapshots}) != 1:
        return {**evidence, "status": "COPYING/UNSTABLE", "reason": "QCOW2 metadata changed during bounded polling"}
    return {**evidence, "status": "READY", "reason": "QCOW2 disk layout and metadata were stable across bounded polls"}


def _connect(server):
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.connect(server.get("ssh_host") or urlsplit(server["url"]).hostname,
                   username=server["ssh_username"], password=server["ssh_password"],
                   timeout=10, auth_timeout=10, banner_timeout=10,
                   allow_agent=False, look_for_keys=False)
    return client


def inspect_image(root: Path, server_name: str, satellite: str, image: str,
                  expected_disks=1, samples=3, interval=5, satellite_key=None,
                  required_names=None):
    """Inspect an image over configured manager SSH and return structured evidence.

    The manager SSH session asks its cluster-known satellite by name to perform the
    local probe. It never copies, repairs, changes permissions, or opens images
    for writing. The finite metadata comparison avoids full-file checksums.
    """
    _valid_name(satellite, "Satellite name")
    _valid_name(image, "Image")
    if type(expected_disks) is not int or expected_disks < 1:
        raise ValueError("Expected QCOW2 disk count must be a positive integer")
    if required_names is not None:
        if (not isinstance(required_names, (list, tuple)) or not required_names
                or any(not isinstance(name, str) or not _NAME.fullmatch(name)
                       or not name.endswith(".qcow2") for name in required_names)
                or len(set(required_names)) != len(required_names)
                or len(required_names) != expected_disks):
            raise ValueError("Required QCOW2 disk names must be unique safe basenames matching disk count")
    if type(samples) is not int or not 2 <= samples <= 5:
        raise ValueError("Satellite image polls must be between 2 and 5")
    if type(interval) not in (int, float) or not 1 <= interval <= 30:
        raise ValueError("Satellite image poll interval must be between 1 and 30 seconds")
    server = load_server(root, server_name, auth="ssh")
    client = None
    snapshots = []
    resolution = None
    try:
        client = _connect(server)
        stdin, stdout, stderr = client.exec_command(resolution_command(satellite, satellite_key), timeout=15)
        stdin.close()
        resolution_output = stdout.read().decode(errors="replace")
        resolution_error = stderr.read().decode(errors="replace")
        if stdout.channel.recv_exit_status() != 0:
            return {"image": image, "expected_qcow2_disks": expected_disks, "poll_count": 0,
                    "snapshots": [], "status": "INVALID",
                    "reason": "Selected satellite address discovery failed: " + resolution_error[:240]}
        target, resolution = _target_from_output(resolution_output)
        if target is None:
            return {"image": image, "expected_qcow2_disks": expected_disks, "poll_count": 0,
                    "snapshots": [], "status": "INVALID",
                    "reason": "Configured SSH transport could not resolve selected satellite " + satellite}
        command = remote_command(target, image)
        for number in range(samples):
            stdin, stdout, stderr = client.exec_command(command, timeout=30)
            stdin.close()
            output = stdout.read().decode(errors="replace")
            error = stderr.read().decode(errors="replace")
            if stdout.channel.recv_exit_status() != 0:
                return {"image": image, "expected_qcow2_disks": expected_disks,
                        "poll_count": number + 1, "snapshots": snapshots, "status": "INVALID",
                        "reason": "Selected satellite image inspection failed: " + error[:240]}
            snapshots.append(parse_snapshot(output))
            if number + 1 < samples:
                time.sleep(interval)
    except (OSError, paramiko.SSHException) as error:
        return {"image": image, "expected_qcow2_disks": expected_disks,
                "poll_count": len(snapshots), "snapshots": snapshots, "status": "INVALID",
                "reason": "Configured SSH transport could not inspect selected satellite: " + str(error)[:240]}
    finally:
        client.close()
    return {**assess_image_snapshots(image, expected_disks, snapshots, required_names),
            "satellite": satellite,
            "target_resolution": resolution}
