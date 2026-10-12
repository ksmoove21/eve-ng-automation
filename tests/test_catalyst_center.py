import json
import ssl
import unittest
from urllib.error import HTTPError
from urllib.request import Request

from eve_lab.catalyst_center import (
    CatalystCenterClient,
    CatalystCenterError,
    CatalystCenterTaskError,
    TaskReference,
    _NoRedirect,
)


class Response:
    def __init__(self, status, body):
        self.status = status
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, *_):
        return self._body if isinstance(self._body, bytes) else json.dumps(self._body).encode()


class Opener:
    def __init__(self, responses):
        self._responses = list(responses)
        self.requests = []
        self.timeouts = []

    def open(self, request, timeout):
        self.requests.append(request)
        self.timeouts.append(timeout)
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return Response(*response)


class CatalystCenterClientTests(unittest.TestCase):
    def client(self, responses, **kwargs):
        return CatalystCenterClient(
            "https://cc.example",
            "user",
            "secret",
            opener=Opener(responses),
            **kwargs,
        )

    def test_authenticates_and_reads_all_pages(self):
        client = self.client(
            [
                (200, {"Token": "token"}),
                (200, {"response": [{"id": "1"}, {"id": "2"}]}),
                (200, {"response": [{"id": "3"}]}),
            ]
        )

        self.assertEqual([item["id"] for item in client.list_all("/dna/example", limit=2)], ["1", "2", "3"])
        self.assertEqual(client._opener.requests[1].get_header("X-auth-token"), "token")
        self.assertIn("offset=3", client._opener.requests[-1].full_url)
        self.assertNotIn("secret", repr(client))

    def test_sends_documented_batch_body(self):
        client = self.client([(200, {"Token": "token"}), (200, {})])

        self.assertEqual(client.request("POST", "/dna/example", body=[{"name": "one"}, {"name": "two"}]), {})
        self.assertEqual(json.loads(client._opener.requests[-1].data), [{"name": "one"}, {"name": "two"}])
        with self.assertRaises(TypeError):
            client.request("POST", "/dna/example", body=["not-an-object"])


    def test_refreshes_once_after_unauthorized_response(self):
        unauthorized = HTTPError("https://cc.example", 401, "Unauthorized", {}, None)
        client = self.client([(200, {"Token": "first"}), unauthorized, (200, {"Token": "second"}), (200, {})])

        self.assertEqual(client.read("/dna/example"), {})
        self.assertEqual(len(client._opener.requests), 4)
        self.assertEqual(client._opener.requests[-1].get_header("X-auth-token"), "second")

    def test_accepts_only_verified_tls_contexts(self):
        verified = ssl.create_default_context()
        client = self.client([], tls_context=verified)
        self.assertIs(client.context, verified)

        no_hostname = ssl.create_default_context()
        no_hostname.check_hostname = False
        with self.assertRaisesRegex(ValueError, "check hostnames"):
            self.client([], tls_context=no_hostname)

        no_verification = ssl.create_default_context()
        no_verification.check_hostname = False
        no_verification.verify_mode = ssl.CERT_NONE
        with self.assertRaisesRegex(ValueError, "require certificates"):
            self.client([], tls_context=no_verification)


    def test_rejects_credential_origins_invalid_paths_and_redirects(self):
        with self.assertRaises(ValueError):
            CatalystCenterClient("http://cc.example", "user", "secret")
        with self.assertRaises(ValueError):
            CatalystCenterClient("https://user:secret@cc.example", "user", "secret")
        client = self.client([])
        with self.assertRaises(ValueError):
            client.read("https://cc.example/dna/example")
        with self.assertRaises(HTTPError) as error:
            _NoRedirect().redirect_request(Request("https://cc.example/dna/example"), None, 302, "Found", {}, "https://other.example")
        self.assertEqual(error.exception.code, 302)

    def test_rejects_response_over_size_limit(self):
        client = self.client([(200, {"Token": "token"}), (200, b"x" * (4 * 1024 * 1024 + 1))])
        with self.assertRaisesRegex(CatalystCenterError, "exceeds 4 MiB"):
            client.read("/dna/example")

    def test_stops_repeated_pagination(self):
        client = self.client(
            [
                (200, {"Token": "token"}),
                (200, {"response": [{"id": "1"}]}),
                (200, {"response": [{"id": "1"}]}),
            ]
        )

        with self.assertRaisesRegex(CatalystCenterError, "repeated"):
            client.list_all("/dna/example", limit=1)

    def test_returns_successful_task_and_preserves_its_id(self):
        clock_values = iter((0, 0, 0, 0))
        client = self.client(
            [(200, {"Token": "token"}), (200, {"response": {"id": "task-1", "endTime": 1}})],
            clock=lambda: next(clock_values),
        )

        status = client.wait_task("task-1", timeout=4)
        self.assertTrue(status.successful)
        self.assertEqual(status.task_id, "task-1")
        self.assertEqual(client._opener.timeouts, [4, 4])
        self.assertEqual(
            CatalystCenterClient.task_reference({"response": {"taskId": "task-1", "url": "/task"}}),
            TaskReference("task-1", "/task"),
        )
        self.assertIsNone(CatalystCenterClient.task_reference({"response": {"id": "resource-1"}}))

    def test_raises_on_failed_malformed_or_timed_out_task(self):
        failed = self.client([(200, {"Token": "token"}), (200, {"response": {"id": "task-1", "endTime": 1, "isError": True}})])
        with self.assertRaises(CatalystCenterTaskError):
            failed.wait_task("task-1")

        malformed = self.client([(200, {"Token": "token"}), (200, {"response": {"id": "task-1", "endTime": 1, "isError": "false"}})])
        with self.assertRaisesRegex(CatalystCenterError, "invalid error state"):
            malformed.wait_task("task-1")

        clock_values = iter((0, 2))
        timed_out = self.client([], clock=lambda: next(clock_values))
        with self.assertRaisesRegex(CatalystCenterTaskError, "timed out"):
            timed_out.wait_task("task-1", timeout=1)
        self.assertFalse(timed_out._opener.requests)

    def test_reads_documented_top_level_object_array(self):
        client = self.client([(200, {"Token": "token"}), (200, [{"deviceUuid": "one"}, {"deviceUuid": "two"}])])

        self.assertEqual(
            client.read_array("/dna/intent/api/v1/file/file-id", operation="Command-runner file"),
            ({"deviceUuid": "one"}, {"deviceUuid": "two"}),
        )
        request = client._opener.requests[-1]
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.get_header("X-auth-token"), "token")

    def test_array_read_is_shape_strict_and_retains_refresh_and_size_protection(self):
        for body in ({"response": []}, ["not-an-object"], "scalar"):
            client = self.client([(200, {"Token": "token"}), (200, body)])
            with self.assertRaisesRegex(CatalystCenterError, "array shape"):
                client.read_array("/dna/intent/api/v1/file/file-id")

        object_read = self.client([(200, {"Token": "token"}), (200, [{"id": "one"}])])
        with self.assertRaisesRegex(CatalystCenterError, "unexpected JSON shape"):
            object_read.read("/dna/intent/api/v1/file/file-id")

        unauthorized = HTTPError("https://cc.example", 401, "Unauthorized", {}, None)
        refreshed = self.client([(200, {"Token": "first"}), unauthorized, (200, {"Token": "second"}), (200, [])])
        self.assertEqual(refreshed.read_array("/dna/intent/api/v1/file/file-id"), ())
        self.assertEqual(refreshed._opener.requests[-1].get_header("X-auth-token"), "second")

        oversized = self.client([(200, {"Token": "token"}), (200, b"[" + b" " * (4 * 1024 * 1024) + b"]")])
        with self.assertRaisesRegex(CatalystCenterError, "exceeds 4 MiB"):
            oversized.read_array("/dna/intent/api/v1/file/file-id")

if __name__ == "__main__":
    unittest.main()
