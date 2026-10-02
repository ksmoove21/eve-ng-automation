"""CLI-backed application-server qualification for Catalyst SD-WAN Manager."""
from dataclasses import dataclass
import re
import time
from typing import Callable


@dataclass(frozen=True)
class ApplicationStatus:
    enabled: bool
    running: bool
    pid: int | None
    uptime_seconds: int | None


@dataclass(frozen=True)
class ReadinessObservation:
    qualified: bool
    reason: str
    pid: int | None
    uptime_seconds: int | None


@dataclass(frozen=True)
class NmsServiceStatus:
    name: str
    enabled: bool
    state: str
    pid: int | None
    uptime_seconds: int | None


def parse_all_nms_status(output):
    """Parse only non-secret service state from request nms all status."""
    pattern = re.compile(
        r"(?m)^(?P<name>[A-Za-z][^\r\n]+)\r?\n"
        r"[ \t]+Enabled:\s*(?P<enabled>true|false)\s*\r?\n"
        r"(?:[ \t]+Message:[^\r\n]*\r?\n)?"
        r"[ \t]+Status:\s*(?P<state>not running|running|waiting|stopped)"
        r"(?:\s+PID:\s*(?P<pid>\d+)\s+for\s+"
        r"(?P<uptime>\d+)s)?\s*$",
        re.I)
    result = []
    for match in pattern.finditer(output):
        result.append(NmsServiceStatus(
            match.group("name").strip(),
            match.group("enabled").lower() == "true",
            match.group("state").lower(),
            int(match.group("pid")) if match.group("pid") else None,
            int(match.group("uptime")) if match.group("uptime") else None))
    if not result:
        raise ValueError("No NMS service status sections found")
    return tuple(result)


def parse_application_status(output):
    section = re.search(r"(?im)^\s*NMS application server\s*$", output)
    if not section:
        raise ValueError("NMS application server section missing")
    tail = output[section.end():]
    enabled = re.search(r"(?im)^\s*Enabled:\s*(true|false)\s*$", tail)
    status = re.search(
        r"(?im)^\s*Status:\s*(not\s+running|running|stopped)"
        r"(?:\s+PID:\s*(\d+)\s+for\s+(\d+)s)?\s*$", tail)
    if not enabled or not status:
        raise ValueError("NMS application server Enabled/Status fields missing")
    return ApplicationStatus(
        enabled.group(1).lower() == "true",
        status.group(1).lower() == "running",
        int(status.group(2)) if status.group(2) else None,
        int(status.group(3)) if status.group(3) else None,
    )


class ApplicationReadiness:
    def __init__(self, minimum_seconds=900):
        if minimum_seconds < 1:
            raise ValueError("minimum_seconds must be positive")
        self.minimum_seconds = minimum_seconds
        self.pid = None
        self.last_uptime = None

    def observe(self, output):
        status = parse_application_status(output)
        if not status.enabled or not status.running:
            self.pid = self.last_uptime = None
            reason = ("application server disabled" if not status.enabled
                      else "application server not running")
            return ReadinessObservation(
                False, reason, status.pid, status.uptime_seconds)
        if status.pid is None or status.uptime_seconds is None:
            self.pid = self.last_uptime = None
            return ReadinessObservation(
                False, "application status lacks PID or uptime",
                status.pid, status.uptime_seconds)
        if self.pid is not None and self.pid != status.pid:
            self.pid, self.last_uptime = status.pid, status.uptime_seconds
            return ReadinessObservation(
                False, "application PID changed; qualification reset",
                status.pid, status.uptime_seconds)
        if self.last_uptime is not None and status.uptime_seconds < self.last_uptime:
            self.pid, self.last_uptime = status.pid, status.uptime_seconds
            return ReadinessObservation(
                False, "application uptime decreased; qualification reset",
                status.pid, status.uptime_seconds)
        self.pid, self.last_uptime = status.pid, status.uptime_seconds
        if status.uptime_seconds < self.minimum_seconds:
            return ReadinessObservation(
                False, "application uptime below qualification threshold",
                status.pid, status.uptime_seconds)
        return ReadinessObservation(
            True, "application server qualified", status.pid,
            status.uptime_seconds)


def wait_for_application_server(read_status: Callable[[], str], *,
                                timeout_seconds=3600, poll_seconds=12,
                                minimum_seconds=900,
                                monotonic=time.monotonic, sleep=time.sleep,
                                on_wait=None):
    if timeout_seconds < 1 or poll_seconds < 1:
        raise ValueError("timeout_seconds and poll_seconds must be positive")
    if on_wait is not None and not callable(on_wait):
        raise TypeError("on_wait must be callable")
    tracker = ApplicationReadiness(minimum_seconds)
    deadline = monotonic() + timeout_seconds
    last_reason = "CLI unavailable"
    while True:
        pid = uptime = None
        try:
            observation = tracker.observe(read_status())
        except (OSError, RuntimeError, ValueError) as error:
            last_reason = ("application status malformed"
                           if isinstance(error, ValueError) else "CLI unavailable")
        else:
            if observation.qualified:
                return observation
            last_reason = observation.reason
            pid, uptime = observation.pid, observation.uptime_seconds
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError(
                "Manager application readiness timed out: " + last_reason)
        if on_wait is not None:
            on_wait(last_reason, pid, uptime)
        sleep(min(poll_seconds, remaining))

