import socket
import unittest

from dataController.security.url_safety import (
    UnsafeUrlError,
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


class FakeResponse:
    def __init__(self, status_code, headers=None, body=b""):
        self.status_code = status_code
        self.headers = headers or {}
        self._body = body
        self.closed = False
        self.url = ""

    def close(self):
        self.closed = True

    def iter_content(self, chunk_size):
        yield self._body


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


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
