"""Secret-safe Manager-local enterprise CA operations for disposable fabrics."""
import base64
import re

from .sdwan_control import ViptelaConsole


_SHELL_PROMPT = r"(?m)^[^\r\n]*[$#]\s*$"
_EXEC_PROMPT = r"(?m)^[A-Za-z0-9_.-]+#\s*$"
_CERTIFICATE = re.compile(
    r"-----BEGIN CERTIFICATE-----\s+.+?\s+-----END CERTIFICATE-----", re.S)
_CSR = re.compile(
    r"-----BEGIN CERTIFICATE REQUEST-----\s+.+?\s+"
    r"-----END CERTIFICATE REQUEST-----", re.S)


def _shell_command(console: ViptelaConsole, command: str, *, timeout=30):
    console.send(command + "; echo SDWAN_EXIT:$?")
    output, _ = console.expect(_SHELL_PROMPT, timeout=timeout, latest=True)
    matches = list(re.finditer(r"(?m)^SDWAN_EXIT:(\d+)\s*$", output))
    if not matches:
        raise RuntimeError("Manager shell command did not report an exit status")
    return matches[-1].group(1), output


def _enter_shell(console):
    console.send("vshell")
    console.expect(_SHELL_PROMPT, timeout=30, latest=True)


def _leave_shell(console):
    console.send("exit")
    console.expect(_EXEC_PROMPT, timeout=30, latest=True)


def ensure_manager_ca(console: ViptelaConsole, organization: str) -> bool:
    """Ensure a valid 2048-bit Manager-local CA without reading its key."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", organization):
        raise ValueError("Manager CA organization must be shell-safe")
    created = False
    _enter_shell(console)
    try:
        complete, _ = _shell_command(
            console, "test -s ~/SDWAN.key && test -s ~/SDWAN.pem")
        if complete != "0":
            key_exists, _ = _shell_command(console, "test -s ~/SDWAN.key")
            certificate_exists, _ = _shell_command(
                console, "test -s ~/SDWAN.pem")
            if key_exists != "0" and certificate_exists == "0":
                raise RuntimeError(
                    "Manager CA certificate exists without its private key")
            commands = ["umask 077"]
            if key_exists != "0":
                commands.append("openssl genrsa -out ~/SDWAN.key 2048")
            commands.append(
                "openssl req -new -x509 -sha256 -days 1825 "
                "-key ~/SDWAN.key -out ~/SDWAN.pem "
                f"-subj '/C=US/ST=CA/L=SanJose/O={organization}/OU=Lab/"
                f"CN={organization}-CA'")
            for command in commands:
                status, _ = _shell_command(console, command, timeout=180)
                if status != "0":
                    raise RuntimeError("Manager-local CA generation failed")
            created = True
        checks = (
            "test -s ~/SDWAN.key && test -s ~/SDWAN.pem",
            "openssl x509 -in ~/SDWAN.pem -noout -checkend 0",
            "test \"$(openssl x509 -in ~/SDWAN.pem -noout -modulus)\" = "
            "\"$(openssl rsa -in ~/SDWAN.key -noout -modulus 2>/dev/null)\"",
        )
        for command in checks:
            status, _ = _shell_command(console, command, timeout=60)
            if status != "0":
                raise RuntimeError("Manager-local CA validation failed")
        return created
    finally:
        _leave_shell(console)


def manager_ca_certificate(console: ViptelaConsole) -> str:
    """Return the public Manager CA certificate; never read its private key."""
    _enter_shell(console)
    try:
        status, output = _shell_command(console, "cat ~/SDWAN.pem")
        blocks = _CERTIFICATE.findall(output)
        if status != "0" or len(blocks) != 1:
            raise RuntimeError("Manager CA certificate was unavailable or ambiguous")
        return blocks[0].strip() + "\n"
    finally:
        _leave_shell(console)


def sign_csr_on_manager(console: ViptelaConsole, csr: str, *, name: str) -> str:
    """Sign one correlated CSR on Manager without exporting the CA key."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", name):
        raise ValueError("CSR correlation name must be shell-safe")
    normalized = csr.replace("\r\n", "\n").strip() + "\n"
    blocks = _CSR.findall(normalized)
    if len(blocks) != 1 or blocks[0].strip() + "\n" != normalized:
        raise ValueError("A single PEM CSR is required")
    encoded = base64.b64encode(normalized.encode("ascii")).decode("ascii")
    csr_path = "/home/admin/" + name + ".csr"
    cert_path = "/home/admin/" + name + ".crt"
    _enter_shell(console)
    try:
        console.send_secret(
            "umask 077; printf %s " + encoded + " | base64 -d > " + csr_path +
            "; echo SDWAN_EXIT:$?")
        staged, _ = console.expect(_SHELL_PROMPT, timeout=60, latest=True)
        if not re.search(r"(?m)^SDWAN_EXIT:0\s*$", staged):
            raise RuntimeError("Manager CSR staging failed")
        command = (
            "test -s ~/SDWAN.key && test -s ~/SDWAN.pem && "
            "openssl req -in " + csr_path + " -noout -verify && "
            "openssl x509 -req -in " + csr_path + " -CA ~/SDWAN.pem "
            "-CAkey ~/SDWAN.key -CAcreateserial -out " + cert_path +
            " -days 1825 -sha256 && openssl verify -CAfile ~/SDWAN.pem " +
            cert_path + " && cat " + cert_path)
        status, output = _shell_command(console, command, timeout=180)
        certificates = _CERTIFICATE.findall(output)
        if status != "0" or len(certificates) != 1:
            raise RuntimeError("Manager-local CSR signing failed")
        return certificates[0].strip() + "\n"
    finally:
        _leave_shell(console)


def install_controller_root(console: ViptelaConsole, certificate: str, *,
                            subject_marker: str) -> str:
    """Stage, install, and read back one enterprise root on a controller."""
    normalized = certificate.replace("\r\n", "\n").strip() + "\n"
    blocks = _CERTIFICATE.findall(normalized)
    if len(blocks) != 1 or blocks[0].strip() + "\n" != normalized:
        raise ValueError("A single PEM root certificate is required")
    if (not isinstance(subject_marker, str) or not subject_marker
            or "\n" in subject_marker or "\r" in subject_marker):
        raise ValueError("A safe root subject marker is required")
    encoded = base64.b64encode(normalized.encode("ascii")).decode("ascii")
    path = "/home/admin/enterprise-root.pem"
    _enter_shell(console)
    try:
        console.send_secret(
            "umask 077; printf %s " + encoded + " | base64 -d > " + path +
            "; test -s " + path + "; openssl x509 -in " + path +
            " -noout -checkend 0; echo SDWAN_EXIT:$?")
        output, _ = console.expect(_SHELL_PROMPT, timeout=60, latest=True)
        if not re.search(r"(?m)^SDWAN_EXIT:0\s*$", output):
            raise RuntimeError("Controller root staging or validation failed")
    finally:
        _leave_shell(console)
    installed = console.command(
        "request root-cert-chain install " + path, timeout=180)
    if "Successfully installed the root certificate chain" not in installed:
        raise RuntimeError("Controller root certificate installation failed")
    readback = console.command(
        "show certificate root-ca-cert | nomore", timeout=60)
    if subject_marker not in readback:
        raise RuntimeError("Controller root certificate read-back failed")
    return path
