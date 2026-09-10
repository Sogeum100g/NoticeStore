import gzip
import io
import socket
import unittest

import requests
from urllib3.response import HTTPResponse

from dataController.security.url_safety import (
    DEFAULT_MAX_DECODED_BYTES,
    DEFAULT_MAX_TRANSFER_BYTES,
    MAX_CONFIGURABLE_RESPONSE_BYTES,
    ResponseTooLargeError,
    UnsafeUrlError,
    load_response_limit_policy,
    safe_request,
    sanitize_outbound_headers,
    validate_public_url,
)


def dns_results(*addresses):
    results = []
    for address in addresses:
        family = socket.AF_INET6 if ":" in address else socket.AF_INET
        sockaddr = (address, 443, 0, 0) if family == socket.AF_INET6 else (address, 443)
        results.append((family, socket.SOCK_STREAM, 6, "", sockaddr))
    return results


class UrlValidationTests(unittest.TestCase):
    def test_only_http_and_https_are_allowed(self):
        with self.assertRaises(UnsafeUrlError):
            validate_public_url("file:///etc/passwd")

    def test_userinfo_is_rejected(self):
        with self.assertRaises(UnsafeUrlError):
            validate_public_url("https://user:password@example.com/notices")

    def test_loopback_private_link_local_and_reserved_literals_are_rejected(self):
        for url in (
            "http://127.0.0.1/",
            "http://10.0.0.1/",
            "http://169.254.169.254/latest/meta-data/",
            "http://[::1]/",
            "http://192.0.2.1/",
        ):
            with self.subTest(url=url), self.assertRaises(UnsafeUrlError):
                validate_public_url(url)

    def test_all_a_and_aaaa_results_must_be_public(self):
        def resolver(*args, **kwargs):
            return dns_results("93.184.216.34", "10.0.0.5")

        with self.assertRaises(UnsafeUrlError):
            validate_public_url("https://example.com/notices", resolver=resolver)

    def test_public_a_and_aaaa_results_are_accepted(self):
        def resolver(*args, **kwargs):
            return dns_results("93.184.216.34", "2606:4700:4700::1111")

        result = validate_public_url(
            "https://Example.com/notices#fragment",
            resolver=resolver,
        )
        self.assertEqual(result.hostname, "example.com")
        self.assertEqual(result.port, 443)
        self.assertNotIn("#fragment", result.url)

    def test_nonstandard_ports_are_rejected(self):
        with self.assertRaises(UnsafeUrlError):
            validate_public_url("https://93.184.216.34:8443/notices")


class HeaderSanitizationTests(unittest.TestCase):
    def test_sensitive_headers_are_removed_case_insensitively(self):
        result = sanitize_outbound_headers(
            {
                "Authorization": "Bearer secret",
                "cookie": "sid=secret",
                "X-CSRF-Token": "secret",
                "Accept": "application/json",
            }
        )
        self.assertEqual(result, {"Accept": "application/json"})


class FakeRaw:
    def __init__(self, wire_sizes):
        self.wire_sizes = list(wire_sizes)
        self.index = -1

    def advance(self):
        self.index += 1

    def tell(self):
        if self.index < 0:
            return 0
        return self.wire_sizes[self.index]


class FakeResponse:
    def __init__(self, status_code, headers=None, body=b"", wire_sizes=None):
        self.status_code = status_code
        self.headers = headers or {}
        self._chunks = body if isinstance(body, list) else [body]
        self.closed = False
        self.url = ""
        if wire_sizes is not None:
            self.raw = FakeRaw(wire_sizes)

    def close(self):
        self.closed = True

    def iter_content(self, chunk_size):
        for chunk in self._chunks:
            if hasattr(self, "raw"):
                self.raw.advance()
            yield chunk


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


def public_validator(url):
    return type("Validated", (), {"url": url, "addresses": ()})()


class ResponseLimitPolicyTests(unittest.TestCase):
    def test_defaults_are_five_mib_and_finite(self):
        policy = load_response_limit_policy({})
        self.assertEqual(policy.max_transfer_bytes, 5 * 1024 * 1024)
        self.assertEqual(policy.max_decoded_bytes, 5 * 1024 * 1024)
        self.assertEqual(policy.max_transfer_bytes, DEFAULT_MAX_TRANSFER_BYTES)
        self.assertEqual(policy.max_decoded_bytes, DEFAULT_MAX_DECODED_BYTES)

    def test_environment_overrides_both_limits(self):
        policy = load_response_limit_policy(
            {
                "CRAWLER_MAX_TRANSFER_BYTES": "1048576",
                "CRAWLER_MAX_DECODED_BYTES": "2097152",
            }
        )
        self.assertEqual(policy.max_transfer_bytes, 1 * 1024 * 1024)
        self.assertEqual(policy.max_decoded_bytes, 2 * 1024 * 1024)

    def test_unbounded_or_excessive_values_fall_back_to_safe_defaults(self):
        policy = load_response_limit_policy(
            {
                "CRAWLER_MAX_TRANSFER_BYTES": "0",
                "CRAWLER_MAX_DECODED_BYTES": str(
                    MAX_CONFIGURABLE_RESPONSE_BYTES + 1
                ),
            }
        )
        self.assertEqual(policy.max_transfer_bytes, DEFAULT_MAX_TRANSFER_BYTES)
        self.assertEqual(policy.max_decoded_bytes, DEFAULT_MAX_DECODED_BYTES)


class BoundedResponseTests(unittest.TestCase):
    @staticmethod
    def _gzip_response(decoded_body: bytes):
        encoded_body = gzip.compress(decoded_body)
        response = requests.Response()
        response.status_code = 200
        response.headers = requests.structures.CaseInsensitiveDict(
            {
                "Content-Type": "text/html; charset=UTF-8",
                "Content-Encoding": "gzip",
            }
        )
        response.raw = HTTPResponse(
            body=io.BytesIO(encoded_body),
            headers=response.headers,
            preload_content=False,
        )
        return response, encoded_body

    def test_real_gzip_decoder_counts_encoded_and_decoded_bytes(self):
        decoded_body = b"A" * 1000
        response, encoded_body = self._gzip_response(decoded_body)

        result = safe_request(
            FakeSession([response]),
            "GET",
            "https://public.example/notices",
            max_transfer_bytes=len(encoded_body) + 1,
            max_response_bytes=len(decoded_body) + 1,
            validator=public_validator,
        )

        self.assertEqual(result.content, decoded_body)
        self.assertEqual(
            result._response_size_metrics.transfer_bytes,
            len(encoded_body),
        )
        self.assertEqual(
            result._response_size_metrics.decoded_bytes,
            len(decoded_body),
        )

    def test_gzip_decoder_stops_at_decoded_limit(self):
        response, encoded_body = self._gzip_response(b"A" * 1000)

        with self.assertRaises(ResponseTooLargeError) as raised:
            safe_request(
                FakeSession([response]),
                "GET",
                "https://public.example/notices",
                max_transfer_bytes=len(encoded_body) + 1,
                max_response_bytes=100,
                validator=public_validator,
            )

        self.assertEqual(raised.exception.limit_kind, "decoded_streamed")
        self.assertEqual(raised.exception.observed_bytes, 101)

    def test_declared_transfer_limit_is_enforced_before_body_read(self):
        response = FakeResponse(
            200,
            {"Content-Length": "6", "Content-Type": "text/html"},
            b"unused",
        )
        with self.assertRaises(ResponseTooLargeError) as raised:
            safe_request(
                FakeSession([response]),
                "GET",
                "https://public.example/notices",
                max_transfer_bytes=5,
                max_response_bytes=10,
                validator=public_validator,
            )

        self.assertTrue(response.closed)
        self.assertEqual(raised.exception.limit_kind, "transfer_declared")
        self.assertEqual(raised.exception.observed_bytes, 6)

    def test_streamed_transfer_and_decoded_limits_are_distinct(self):
        response = FakeResponse(
            200,
            {
                "Content-Type": "text/html; charset=UTF-8",
                "Content-Encoding": "gzip",
            },
            b"decoded",
            wire_sizes=[6],
        )
        with self.assertRaises(ResponseTooLargeError) as raised:
            safe_request(
                FakeSession([response]),
                "GET",
                "https://public.example/notices",
                max_transfer_bytes=5,
                max_response_bytes=20,
                validator=public_validator,
            )

        self.assertEqual(raised.exception.limit_kind, "transfer_streamed")
        self.assertIn("content_encoding=gzip", str(raised.exception))

    def test_decoded_limit_reports_observed_size_and_response_metadata(self):
        response = FakeResponse(
            200,
            {
                "Content-Type": "application/json",
                "Content-Encoding": "gzip",
            },
            b"decoded",
            wire_sizes=[4],
        )
        with self.assertRaises(ResponseTooLargeError) as raised:
            safe_request(
                FakeSession([response]),
                "GET",
                "https://public.example/notices",
                max_transfer_bytes=20,
                max_response_bytes=5,
                validator=public_validator,
            )

        error = raised.exception
        self.assertEqual(error.limit_kind, "decoded_streamed")
        self.assertEqual(error.observed_bytes, 7)
        self.assertEqual(error.limit_bytes, 5)
        self.assertIn("content_type=application/json", str(error))

    def test_success_exposes_transfer_and_decoded_metrics(self):
        response = FakeResponse(
            200,
            {"Content-Type": "text/html", "Content-Encoding": "gzip"},
            b"decoded-body",
            wire_sizes=[5],
        )
        result = safe_request(
            FakeSession([response]),
            "GET",
            "https://public.example/notices",
            max_transfer_bytes=20,
            max_response_bytes=20,
            validator=public_validator,
        )

        metrics = result._response_size_metrics
        self.assertEqual(metrics.transfer_bytes, 5)
        self.assertEqual(metrics.decoded_bytes, 12)
        self.assertEqual(metrics.content_encoding, "gzip")


class RedirectValidationTests(unittest.TestCase):
    def test_every_redirect_hop_is_validated(self):
        first = FakeResponse(302, {"Location": "http://127.0.0.1/admin"})
        session = FakeSession([first])
        validated_urls = []

        def validator(url):
            validated_urls.append(url)
            if "127.0.0.1" in url:
                raise UnsafeUrlError("blocked")
            return type("Validated", (), {"url": url})()

        with self.assertRaises(UnsafeUrlError):
            safe_request(
                session,
                "GET",
                "https://public.example/start",
                validator=validator,
            )

        self.assertEqual(
            validated_urls,
            [
                "https://public.example/start",
                "http://127.0.0.1/admin",
            ],
        )


if __name__ == "__main__":
    unittest.main()
