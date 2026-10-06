"""Transactional IOS XE Catalyst SD-WAN cEdge console primitives."""
import hashlib
from dataclasses import dataclass
import re
import ssl

from cryptography import x509

from .device_console import Console


_CONFIG_PROMPT = r"(?m)^[A-Za-z0-9_.-]+\(config[^)]*\)#\s*$"
_EXEC_PROMPT = r"(?m)^[A-Za-z0-9_.-]+#\s*$"
_ANY_PROMPT = r"(?m)^[A-Za-z0-9_.-]+(?:\(config[^)]*\))?#\s*$"
_REJECTED = re.compile(
    r"(?im)^\s*(?:error:|failed:|syntax error:|invalid input|commit failed|"
    r"aborted:|%\s*(?:error|invalid|incomplete|ambiguous))")
_CERTIFICATE = re.compile(
    r"-----BEGIN CERTIFICATE-----\s+.+?\s+-----END CERTIFICATE-----", re.S)


def _safe_value(value, name, pattern=r"[A-Za-z0-9_.-]+"):
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise ValueError(name + " is invalid")
    return value


def absolute_scp_source(username, host, path):
    """Build the IOS XE SCP absolute-path form (two slashes after host)."""
    user = _safe_value(username, "SCP username")
    address = _safe_value(host, "SCP host", r"[A-Za-z0-9_.:-]+")
    if (not isinstance(path, str) or not path.startswith("/")
            or not re.fullmatch(r"/[A-Za-z0-9_./-]+", path)
            or ".." in path.split("/")):
        raise ValueError("SCP source must be a safe absolute path")
    return "scp://" + user + "@" + address + "/" + path


def certificate_sha256(certificate):
    """Parse one PEM certificate and return its DER SHA-256 fingerprint."""
    if not isinstance(certificate, str):
        raise ValueError("Certificate must be PEM text")
    normalized = certificate.replace("\r\n", "\n").strip() + "\n"
    blocks = _CERTIFICATE.findall(normalized)
    if len(blocks) != 1 or blocks[0].strip() + "\n" != normalized:
        raise ValueError("Exactly one PEM certificate is required")
    x509.load_pem_x509_certificate(normalized.encode("ascii"))
    return hashlib.sha256(ssl.PEM_cert_to_DER_cert(normalized)).hexdigest()


@dataclass(frozen=True)
class EdgeStage:
    name: str
    commands: tuple[str, ...]


def stages_from_edge_plan(plan):
    """Validate and normalize the compiled owner-baseline cEdge stages."""
    if not isinstance(plan, dict) or plan.get("adapter") != "c8000v-sdwan":
        raise ValueError("Expected a compiled c8000v-sdwan plan")
    result = []
    for item in plan.get("operations", []):
        if item.get("mode") != "config-transaction":
            continue
        if (not re.fullmatch(r"[a-z][a-z0-9-]*", str(item.get("name", "")))
                or item.get("commit") is not True
                or not isinstance(item.get("commands"), list)
                or not item["commands"]
                or any(not isinstance(command, str) or not command
                       or "\n" in command or "\r" in command
                       for command in item["commands"])):
            raise ValueError("Invalid compiled cEdge stage")
        result.append(EdgeStage(item["name"], tuple(item["commands"])))
    names = [item.name for item in result]
    if names not in (["identity", "transport"],
                     ["identity", "transport", "service-lan"]):
        raise ValueError(
            "cEdge stages must be identity, transport, with optional service-lan")
    return tuple(result)


def _normalized_config(output):
    # Remove this exact asynchronous diagnostic, retaining the following line.
    output = re.sub(
        r"(?:\*?[A-Z][a-z]{2}\s+\d+\s+"
        r"\d{2}:\d{2}:\d{2}(?:\.\d+)?\s*:\s*)?"
        r"%SMART_LIC-2-PLATFORM_ERROR: Smart Licensing has encountered an "
        r"internal software error\. Contact TAC: The platform provided UDI "
        r"list has invalid values: ; udi_sn is empty; udi_sn is null or empty "
        r"for valid udi_pid", "", output)
    return "\n".join(" ".join(line.replace('"', '').split())
                     for line in output.splitlines())


def missing_desired_commands(output, stages):
    """Return desired configuration lines absent from SD-WAN read-back."""
    normalized = _normalized_config(output)
    omitted = {"exit", "no shutdown"}
    desired = [" ".join(command.replace('"', '').split())
               for stage in stages for command in stage.commands
               if command not in omitted]
    return tuple(command for command in desired
                 if not re.search(r"(?m)^\s*" + re.escape(command) + r"\s*$",
                                  normalized))


class CedgeConsole(Console):
    """Apply independently committed IOS XE SD-WAN config transactions."""

    def configure_stage(self, stage, timeout=90):
        if not isinstance(stage, EdgeStage):
            raise TypeError("stage must be an EdgeStage")
        self.send("config-transaction")
        self.expect(_CONFIG_PROMPT, timeout=timeout, latest=True,
                    redisplay=True)
        for index, command in enumerate(stage.commands, start=1):
            self.send(command)
            try:
                output, _ = self.expect(
                    _CONFIG_PROMPT, timeout=timeout, latest=True,
                    redisplay=True)
            except RuntimeError as error:
                raise RuntimeError(
                    "cEdge " + stage.name + " command " + str(index) +
                    " did not return a prompt") from error
            if _REJECTED.search(output):
                self.send("abort")
                self.expect(_EXEC_PROMPT, timeout=timeout, latest=True)
                raise RuntimeError(
                    "cEdge rejected " + stage.name + " command " +
                    str(index) + "; transaction aborted")
        self.send("commit")
        output, match = self.expect(
            _ANY_PROMPT, timeout=max(timeout, 300), latest=True)
        if _REJECTED.search(output):
            if "(config" in match.group():
                self.send("abort")
                self.expect(_EXEC_PROMPT, timeout=timeout, latest=True)
            raise RuntimeError(
                "cEdge " + stage.name + " commit rejected")
        if "(config" in match.group():
            self.send("end")
            self.expect(_EXEC_PROMPT, timeout=timeout, latest=True,
                        redisplay=True)

    def copy_scp_absolute(self, username, host, source_path, destination,
                          password, fingerprints, timeout=120):
        """Copy one file over SCP only after matching the server host key."""
        source = absolute_scp_source(username, host, source_path)
        target = _safe_value(
            destination, "SCP destination", r"bootflash:[A-Za-z0-9_./-]+")
        if (not isinstance(password, str) or not password
                or any(char in password for char in "\r\n")):
            raise ValueError("SCP password is invalid")
        if (not isinstance(fingerprints, set) or not fingerprints
                or any(not re.fullmatch(r"SHA256:[A-Za-z0-9+/]+", item)
                       for item in fingerprints)):
            raise ValueError("Trusted SCP fingerprints are required")
        self.send("copy " + source + " " + target)
        transcript = ""
        seen = set()
        pattern = (
            r"(?im:^[^\n]*password:\s*$|^Destination filename[^\n]*\?\s*$|"
            r"^.*continue connecting[^\n]*\?\s*$)|"
            r"(?m:^[A-Za-z0-9_.-]+#\s*$)")
        for _ in range(8):
            output, match = self.expect(pattern, timeout=timeout, latest=True)
            transcript += output
            prompt = match.group().strip()
            if prompt.endswith("#"):
                # IOS licensing diagnostics are unrelated to the SCP result.
                # Retain actual transfer errors and require a copied-byte result.
                transfer_output = re.sub(
                    r"(?:\*?[A-Z][a-z]{2}\s+\d+\s+"
                    r"\d{2}:\d{2}:\d{2}(?:\.\d+)?\s*:\s*)?"
                    r"%SMART_LIC-\d+-[A-Z0-9_]+:[^\n]*", "", transcript)
                if (not re.search(r"\d+ bytes copied", transcript, re.I)
                        or re.search(r"(?im)permission denied|connection refused|"
                                     r"no such file|error|failed|timed out", transfer_output)):
                    raise RuntimeError("SCP copy did not complete successfully")
                return
            lower = prompt.lower()
            stage = ("password" if lower.endswith("password:")
                     else "filename" if lower.startswith("destination filename")
                     else "hostkey")
            if stage in seen:
                raise RuntimeError("SCP repeated an interactive prompt")
            seen.add(stage)
            if stage == "hostkey":
                reported = set(re.findall(
                    r"SHA256:[A-Za-z0-9+/]+", transcript))
                if not reported.intersection(fingerprints):
                    self.send("no")
                    raise RuntimeError("SCP host fingerprint did not match")
                self.send("yes")
            elif stage == "password":
                self.send_secret(password)
            else:
                self.send("")
        raise RuntimeError("SCP prompt sequence did not complete")

    def read_certificate_file(self, path, timeout=60):
        """Require a nonzero, single parseable PEM certificate file."""
        safe_path = _safe_value(
            path, "certificate path", r"bootflash:[A-Za-z0-9_./-]+")
        directory = self.command("dir " + safe_path, timeout=timeout)
        filename = safe_path.rsplit("/", 1)[-1].split(":", 1)[-1]
        size_match = re.search(
            r"(?m)^\s*\d+\s+-\S+-\s+(\d+)\s+.*" +
            re.escape(filename) + r"\s*$", directory)
        if not size_match or int(size_match.group(1)) <= 0:
            raise RuntimeError("Certificate file is absent or zero bytes")
        output = self.command("more " + safe_path, timeout=timeout)
        blocks = _CERTIFICATE.findall(output)
        if len(blocks) != 1:
            raise RuntimeError("Certificate file does not contain one PEM certificate")
        certificate = blocks[0].strip() + "\n"
        certificate_sha256(certificate)
        return certificate, int(size_match.group(1))

    def install_root(self, path, subject_marker, timeout=180):
        """Install and read back the cEdge enterprise root chain."""
        safe_path = _safe_value(
            path, "certificate path", r"bootflash:[A-Za-z0-9_./-]+")
        if not isinstance(subject_marker, str) or not subject_marker.strip():
            raise ValueError("Root subject marker is required")
        installed = self.command(
            "request platform software sdwan root-cert-chain install " +
            safe_path, timeout=timeout)
        if not re.search(r"success|ROOT_CERT_CHAIN_INSTALLED", installed, re.I):
            raise RuntimeError("Root-chain installation did not report success")
        readback = self.command(
            "show sdwan certificate root-ca-cert", timeout=timeout)
        if subject_marker not in readback:
            raise RuntimeError("Installed root did not read back")

    def activate_payg(self, chassis, token, on_attempt, timeout=600):
        """Submit one correlated PAYG activation while discarding secret output."""
        chassis = _safe_value(chassis, "PAYG chassis")
        if (not isinstance(token, str) or not token
                or any(char in token for char in "\r\n")):
            raise ValueError("PAYG token is invalid")
        if not callable(on_attempt):
            raise TypeError("on_attempt must be callable")
        on_attempt()
        self.send_secret(
            "request platform software sdwan vedge_cloud activate "
            "chassis-number " + chassis + " token " + token)
        # Intentionally discard all returned text: terminal wrapping can echo
        # secret material with backspace overstrikes that defeat substitution.
        self.expect(_EXEC_PROMPT, timeout=timeout, latest=True, redisplay=True)
