"""Catalyst Center HTTPS transport, pagination, and task primitives."""
from __future__ import annotations

import base64
import json
import ssl
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

_MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class CatalystCenterError(RuntimeError):
    """A safe, context-only failure from the Catalyst Center API."""

    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


class CatalystCenterTaskError(CatalystCenterError):
    """A Catalyst Center asynchronous task failed or exceeded its deadline."""


@dataclass(frozen=True)
class TaskReference:
    task_id: str
    url: str | None = None


@dataclass(frozen=True)
class TaskStatus:
    task_id: str
    completed: bool
    successful: bool
    error: bool
    end_time: int | None


def _decode(raw: bytes, operation: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, ValueError) as error:
        raise CatalystCenterError(f"{operation} returned invalid JSON") from error
    if not isinstance(value, dict):
        raise CatalystCenterError(f"{operation} returned an unexpected JSON shape")
    return value


class _NoRedirect(HTTPRedirectHandler):
    """Prevent credential-bearing requests from following a new origin."""

    def redirect_request(self, request, file, code, message, headers, new_url):
        raise HTTPError(request.full_url, code, "redirect prohibited", headers, file)


class CatalystCenterClient:
    """Small, generic HTTPS API client; it has no resource reconciliation logic."""

    def __init__(
        self,
        url: str,
        username: str,
        password: str,
        *,
        certificate: str | None = None,
        tls_context: ssl.SSLContext | None = None,
        timeout: float = 15,
        opener: Any | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Catalyst Center URL must be an HTTPS origin")
        if not username or not password or timeout <= 0:
            raise ValueError("Catalyst Center username, password, and positive timeout are required")

        self.url = url.rstrip("/")
        self._username = username
        self._password = password
        self.timeout = timeout
        self._clock = clock
        self._sleep = sleep
        self._token: str | None = None
        if certificate and tls_context:
            raise ValueError("certificate and tls_context are mutually exclusive")
        context = tls_context or (ssl.create_default_context(cafile=certificate) if certificate else ssl.create_default_context())
        if not isinstance(context, ssl.SSLContext):
            raise TypeError("tls_context must be an SSLContext")
        if context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname:
            raise ValueError("tls_context must require certificates and check hostnames")
        self.context = context
        self._opener = opener or build_opener(_NoRedirect(), HTTPSHandler(context=context))

    def _open(
        self,
        request: Request,
        operation: str,
        timeout: float | None = None,
        deadline: float | None = None,
    ) -> tuple[int, bytes]:
        request_timeout = self.timeout if timeout is None else min(timeout, self.timeout)
        if deadline is not None:
            request_timeout = min(request_timeout, deadline - self._clock())
        if request_timeout <= 0:
            raise CatalystCenterError(f"{operation} exceeded its deadline")
        try:
            with self._opener.open(request, timeout=request_timeout) as response:
                raw = response.read(_MAX_RESPONSE_BYTES + 1)
                if len(raw) > _MAX_RESPONSE_BYTES:
                    raise CatalystCenterError(f"{operation} response exceeds 4 MiB")
                return response.status, raw
        except HTTPError as error:
            raise CatalystCenterError(f"{operation} failed: HTTP {error.code}", error.code) from None
        except (OSError, ssl.SSLError, URLError) as error:
            raise CatalystCenterError(f"{operation} transport failed: {type(error).__name__}") from error

    def authenticate(self, *, timeout: float | None = None, deadline: float | None = None) -> None:
        encoded = base64.b64encode(f"{self._username}:{self._password}".encode()).decode()
        status, raw = self._open(
            Request(
                f"{self.url}/dna/system/api/v1/auth/token",
                method="POST",
                headers={"Accept": "application/json", "Authorization": f"Basic {encoded}"},
            ),
            "Catalyst Center authentication",
            timeout,
            deadline,
        )
        token = _decode(raw, "Catalyst Center authentication").get("Token") if status == 200 else None
        if not isinstance(token, str) or not token:
            raise CatalystCenterError("Catalyst Center authentication failed", status)
        self._token = token

    @staticmethod
    def _path(path: str) -> None:
        if not path.startswith("/") or "//" in path[1:] or "?" in path or "#" in path:
            raise ValueError("Catalyst Center API path must be an absolute single-slash path")

    def request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        body: dict[str, Any] | list[dict[str, Any]] | None = None,
        operation: str = "Catalyst Center request",
        timeout: float | None = None,
        deadline: float | None = None,
    ) -> dict[str, Any]:
        self._path(path)
        if timeout is not None and timeout <= 0:
            raise ValueError("Catalyst Center request timeout must be positive")
        if not self._token:
            self.authenticate(timeout=timeout, deadline=deadline)
        if body is not None and (
            not isinstance(body, (dict, list))
            or (isinstance(body, list) and not all(isinstance(item, dict) for item in body))
        ):
            raise TypeError("Catalyst Center request body must be an object or a list of objects")
        data = None if body is None else json.dumps(body, separators=(",", ":")).encode()
        suffix = f"?{urlencode(query, doseq=True)}" if query else ""
        for retry in range(2):
            headers = {"Accept": "application/json", "X-Auth-Token": self._token}
            if data is not None:
                headers["Content-Type"] = "application/json"
            try:
                status, raw = self._open(
                    Request(f"{self.url}{path}{suffix}", data=data, method=method.upper(), headers=headers),
                    operation,
                    timeout,
                    deadline,
                )
            except CatalystCenterError as error:
                if error.code == 401 and retry == 0:
                    self._token = None
                    self.authenticate(timeout=timeout, deadline=deadline)
                    continue
                raise
            if not 200 <= status < 300:
                raise CatalystCenterError(f"{operation} failed: HTTP {status}", status)
            return _decode(raw, operation)
        raise AssertionError("unreachable")

    def read(
        self,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        operation: str = "Catalyst Center read",
        timeout: float | None = None,
        deadline: float | None = None,
    ) -> dict[str, Any]:
        """Perform one generic read; resource-specific planning stays with its adapter."""
        return self.request("GET", path, query=query, operation=operation, timeout=timeout, deadline=deadline)

    def list_all(
        self,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        item_field: str = "response",
        limit: int = 100,
        start_offset: int = 1,
        operation: str = "Catalyst Center list",
    ) -> tuple[dict[str, Any], ...]:
        if type(limit) is not int or limit < 1 or type(start_offset) is not int or start_offset < 0:
            raise ValueError("limit and offset must be valid")
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        offset = start_offset
        while True:
            page = self.read(
                path,
                query={**(query or {}), "offset": offset, "limit": limit},
                operation=operation,
            ).get(item_field)
            if not isinstance(page, list) or not all(isinstance(item, dict) for item in page):
                raise CatalystCenterError(f"{operation} returned invalid page")
            marker = json.dumps(page, sort_keys=True, separators=(",", ":"))
            if page and marker in seen:
                raise CatalystCenterError(f"{operation} repeated a pagination page")
            seen.add(marker)
            items.extend(page)
            if len(page) < limit:
                return tuple(items)
            offset += len(page)

    @staticmethod
    def task_reference(response: dict[str, Any]) -> TaskReference | None:
        value = response.get("response", response)
        if not isinstance(value, dict):
            return None
        task_id = value.get("taskId")
        url = value.get("url")
        if task_id is None:
            return None
        if not isinstance(task_id, str) or not task_id or "/" in task_id or not isinstance(url, (str, type(None))):
            raise CatalystCenterError("Catalyst Center mutation returned invalid task reference")
        return TaskReference(task_id, url)

    def task(self, task_id: str, *, timeout: float | None = None, deadline: float | None = None) -> TaskStatus:
        if not isinstance(task_id, str) or not task_id or "/" in task_id:
            raise ValueError("Catalyst Center task ID is required")
        value = self.read(
            f"/dna/intent/api/v1/task/{task_id}", operation="Catalyst Center task", timeout=timeout, deadline=deadline
        ).get("response")
        if not isinstance(value, dict) or str(value.get("id", task_id)) != task_id:
            raise CatalystCenterError("Catalyst Center task returned invalid response")
        end_time = value.get("endTime")
        if end_time is not None and (type(end_time) is not int or end_time < 0):
            raise CatalystCenterError("Catalyst Center task returned invalid end time")
        error = value.get("isError", False)
        if not isinstance(error, bool):
            raise CatalystCenterError("Catalyst Center task returned invalid error state")
        completed = end_time is not None
        return TaskStatus(task_id, completed, completed and not error, error, end_time)

    def wait_task(self, task: str | TaskReference, *, timeout: float = 900, poll_seconds: float = 5) -> TaskStatus:
        """Wait no longer than the deadline plus socket scheduling overhead."""
        task_id = task.task_id if isinstance(task, TaskReference) else task
        if timeout <= 0 or poll_seconds <= 0:
            raise ValueError("task timeout and poll interval must be positive")
        deadline = self._clock() + timeout
        while True:
            remaining = deadline - self._clock()
            if remaining <= 0:
                raise CatalystCenterTaskError(f"Catalyst Center task timed out: {task_id}")
            status = self.task(task_id, deadline=deadline)
            if status.error:
                raise CatalystCenterTaskError(f"Catalyst Center task failed: {task_id}")
            if status.completed:
                return status
            remaining = deadline - self._clock()
            if remaining <= 0:
                raise CatalystCenterTaskError(f"Catalyst Center task timed out: {task_id}")
            self._sleep(min(poll_seconds, remaining))
