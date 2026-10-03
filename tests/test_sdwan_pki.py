"""Manager-local enterprise CA behavior."""
import unittest

from eve_lab.sdwan_pki import (
    ensure_manager_ca, install_controller_root, manager_ca_certificate,
    sign_csr_on_manager,
)


CERT = """-----BEGIN CERTIFICATE-----
QUJD
-----END CERTIFICATE-----
"""
CSR = """-----BEGIN CERTIFICATE REQUEST-----
QUJD
-----END CERTIFICATE REQUEST-----
"""


class FakeConsole:
    def __init__(self, outputs, commands=()):
        self.outputs = iter(outputs)
        self.commands = iter(commands)
        self.sent = []
        self.secrets = []

    def send(self, value):
        self.sent.append(value)

    def send_secret(self, value):
        self.secrets.append("<secret>")

    def expect(self, *_args, **_kwargs):
        return next(self.outputs), None

    def command(self, *_args, **_kwargs):
        return next(self.commands)


def shell_outputs(*statuses):
    result = ["manager:~$"]
    for status in statuses:
        result.append("SDWAN_EXIT:" + str(status) + "\nmanager:~$")
    result.append("manager#")
    return result


class ManagerPkiTests(unittest.TestCase):
    def test_existing_ca_is_validated_and_shell_is_exited(self):
        console = FakeConsole(shell_outputs(0, 0, 0, 0))
        self.assertFalse(ensure_manager_ca(console, "nwl-lab-sdwan"))
        self.assertEqual(console.sent[-1], "exit")
        self.assertFalse(console.secrets)

    def test_certificate_without_key_fails_closed(self):
        console = FakeConsole(shell_outputs(1, 1, 0))
        with self.assertRaisesRegex(RuntimeError, "without its private key"):
            ensure_manager_ca(console, "nwl-lab-sdwan")
        self.assertEqual(console.sent[-1], "exit")

    def test_existing_key_recovers_missing_certificate(self):
        console = FakeConsole(shell_outputs(
            1, 0, 1, 0, 0, 0, 0, 0))
        self.assertTrue(ensure_manager_ca(console, "nwl-lab-sdwan"))
        self.assertFalse(any("genrsa" in command for command in console.sent))
        self.assertEqual(console.sent[-1], "exit")

    def test_reads_single_public_certificate_and_exits_shell(self):
        console = FakeConsole([
            "manager:~$", CERT + "\nSDWAN_EXIT:0\nmanager:~$", "manager#"])
        self.assertEqual(manager_ca_certificate(console), CERT)
        self.assertEqual(console.sent[-1], "exit")

    def test_signs_valid_csr_secret_safely_and_returns_one_certificate(self):
        console = FakeConsole([
            "manager:~$", "SDWAN_EXIT:0\nmanager:~$",
            CERT + "\nSDWAN_EXIT:0\nmanager:~$", "manager#"])
        self.assertEqual(sign_csr_on_manager(console, CSR, name="manager"), CERT)
        self.assertEqual(console.secrets, ["<secret>"])
        self.assertNotIn(CSR, "\n".join(console.sent))
        self.assertEqual(console.sent[-1], "exit")

    def test_rejects_ambiguous_csr_before_shell_entry(self):
        console = FakeConsole([])
        with self.assertRaises(ValueError):
            sign_csr_on_manager(console, CSR + CSR, name="manager")
        self.assertFalse(console.sent)

    def test_controller_root_requires_install_and_readback(self):
        console = FakeConsole(
            ["controller:~$", "SDWAN_EXIT:0\ncontroller:~$", "controller#"],
            ["Successfully installed the root certificate chain",
             "Subject: CN=nwl-lab-sdwan-CA"])
        path = install_controller_root(
            console, CERT, subject_marker="CN=nwl-lab-sdwan-CA")
        self.assertEqual(path, "/home/admin/enterprise-root.pem")
        self.assertEqual(console.secrets, ["<secret>"])
        self.assertNotIn(CERT, "\n".join(console.sent))

    def test_controller_root_refuses_command_marker_without_readback(self):
        console = FakeConsole(
            ["controller:~$", "SDWAN_EXIT:0\ncontroller:~$", "controller#"],
            ["Successfully installed the root certificate chain", "other"])
        with self.assertRaisesRegex(RuntimeError, "read-back"):
            install_controller_root(
                console, CERT, subject_marker="CN=nwl-lab-sdwan-CA")


if __name__ == "__main__":
    unittest.main()
