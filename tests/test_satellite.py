import base64
import json
import unittest

from eve_lab.satellite import (
    _target_from_output, assess_image_snapshots, console_command, parse_snapshot,
    remote_command, resolution_command, satellite_member,
)


def snapshot(files=(("boot.qcow2", 1024, 10),), writer=False, qemu_format="qcow2"):
    lines = ["STATE|PRESENT", "WRITER|" + ("1" if writer else "0")]
    for name, size, mtime in files:
        lines.append(f"FILE|{name}|{size}|{mtime}")
        details = base64.b64encode(json.dumps({"format": qemu_format, "virtual-size": 4096}).encode()).decode()
        lines.append(f"QEMU|{name}|{details}")
    return parse_snapshot("\n".join(lines))


class SatelliteImageTests(unittest.TestCase):
    def test_stable_valid_qcow2_layout_is_ready(self):
        evidence = assess_image_snapshots("image", 1, [snapshot(), snapshot()])
        self.assertEqual(evidence["status"], "READY")
        self.assertEqual(evidence["snapshots"][0]["files"][0]["format"], "qcow2")

    def test_size_or_mtime_change_is_copying_unstable(self):
        evidence = assess_image_snapshots("image", 1, [snapshot(), snapshot(files=(("boot.qcow2", 2048, 11),))])
        self.assertEqual(evidence["status"], "COPYING/UNSTABLE")
        self.assertIn("metadata changed", evidence["reason"])

    def test_active_writer_is_copying_unstable(self):
        evidence = assess_image_snapshots("image", 1, [snapshot(writer=True), snapshot()])
        self.assertEqual(evidence["status"], "COPYING/UNSTABLE")

    def test_missing_directory_or_required_disk_is_missing(self):
        missing_directory = parse_snapshot("STATE|MISSING")
        self.assertEqual(assess_image_snapshots("image", 1, [missing_directory, missing_directory])["status"], "MISSING")
        self.assertEqual(assess_image_snapshots("image", 2, [snapshot(), snapshot()])["status"], "MISSING")

    def test_qemu_img_error_or_non_qcow_format_is_invalid(self):
        details = base64.b64encode(b"unrecognized image").decode()
        broken = parse_snapshot("STATE|PRESENT\nWRITER|0\nFILE|boot.qcow2|1024|10\nQEMU_ERROR|boot.qcow2|" + details)
        self.assertEqual(assess_image_snapshots("image", 1, [broken, broken])["status"], "INVALID")
        raw = snapshot(qemu_format="raw")
        self.assertEqual(assess_image_snapshots("image", 1, [raw, raw])["status"], "INVALID")

    def test_wireguard_resolution_uses_inventory_key_without_exposing_config(self):
        command = resolution_command("eve-sat03", "VTxVhflwGkuBOsZs2kfD51KwG+1i5lxHywHOvjcUWCY=")
        self.assertIn("wg show wg0 dump", command)
        self.assertEqual(_target_from_output("TARGET|10.42.0.3|wireguard"), ("10.42.0.3", "wireguard"))
        self.assertEqual(_target_from_output("TARGET||wireguard"), (None, "wireguard"))
        with self.assertRaises(ValueError):
            resolution_command("eve-sat03", "invalid; key")

    def test_manager_mediated_command_is_strict_and_rejects_injection(self):
        command = remote_command("eve-sat03", "nd-9.3.2.1c")
        self.assertIn("StrictHostKeyChecking=yes", command)
        self.assertIn("BatchMode=yes", command)
        with self.assertRaises(ValueError):
            remote_command("eve-sat03;touch", "image")
        with self.assertRaises(ValueError):
            remote_command("eve-sat03", "../image")
    def test_satellite_console_command_is_strict_and_local_to_member(self):
        command = console_command("172.30.130.3", 48469)
        self.assertIn("StrictHostKeyChecking=yes", command)
        self.assertIn("172.30.130.3", command)
        self.assertIn("telnet 127.0.0.1 48469", command)
        with self.assertRaises(ValueError):
            console_command("sat03;touch", 48469)
        with self.assertRaises(ValueError):
            console_command("172.30.130.3", 0)

    def test_satellite_member_requires_one_online_non_manager_member(self):
        cluster = {"3": {"id": 3, "name": "eve-sat03", "online": 1}}
        self.assertEqual(satellite_member(cluster, 3)["name"], "eve-sat03")
        cluster["3"]["online"] = 0
        with self.assertRaisesRegex(RuntimeError, "not online"):
            satellite_member(cluster, 3)
        with self.assertRaises(ValueError):
            satellite_member(cluster, 0)
