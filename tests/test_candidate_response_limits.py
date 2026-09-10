import unittest

from dataController.security.url_safety import (
    ResponseLimitPolicy,
    ResponseTooLargeError,
)
from dataController.selector.candidate_collector import (
    ABORT_RESOURCE_TYPES,
    SKIP_RESOURCE_TYPES,
    _read_bounded_response_text,
)


class FakePlaywrightResponse:
    def __init__(self, body: bytes, headers=None):
        self._body = body
        self.headers = headers or {}

    async def body(self):
        return self._body


class FakePlaywrightRequest:
    def __init__(self, response_body_size: int):
        self.response_body_size = response_body_size

    async def sizes(self):
        return {"responseBodySize": self.response_body_size}


class CandidateResponseLimitTests(unittest.IsolatedAsyncioTestCase):
    def test_stylesheets_load_for_lazy_routes_but_are_not_candidates(self):
        self.assertNotIn("stylesheet", ABORT_RESOURCE_TYPES)
        self.assertIn("stylesheet", SKIP_RESOURCE_TYPES)

    async def test_chunked_body_cannot_bypass_decoded_limit(self):
        response = FakePlaywrightResponse(
            b"123456",
            {
                "content-type": "text/html; charset=UTF-8",
                "content-encoding": "gzip",
            },
        )
        with self.assertRaises(ResponseTooLargeError) as raised:
            await _read_bounded_response_text(
                response,
                FakePlaywrightRequest(response_body_size=3),
                ResponseLimitPolicy(
                    max_transfer_bytes=10,
                    max_decoded_bytes=5,
                ),
            )

        self.assertEqual(raised.exception.limit_kind, "decoded_buffered")
        self.assertEqual(raised.exception.observed_bytes, 6)

    async def test_playwright_encoded_size_enforces_transfer_limit(self):
        response = FakePlaywrightResponse(
            b"body",
            {
                "content-type": "application/json",
                "content-encoding": "gzip",
            },
        )
        with self.assertRaises(ResponseTooLargeError) as raised:
            await _read_bounded_response_text(
                response,
                FakePlaywrightRequest(response_body_size=6),
                ResponseLimitPolicy(
                    max_transfer_bytes=5,
                    max_decoded_bytes=10,
                ),
            )

        self.assertEqual(raised.exception.limit_kind, "transfer_measured")

    async def test_success_returns_text_and_both_sizes(self):
        response = FakePlaywrightResponse(
            "공지 목록".encode("euc-kr"),
            {"content-type": "text/html; charset=euc-kr"},
        )
        text, transfer_bytes, decoded_bytes = await _read_bounded_response_text(
            response,
            FakePlaywrightRequest(response_body_size=7),
            ResponseLimitPolicy(
                max_transfer_bytes=20,
                max_decoded_bytes=20,
            ),
        )

        self.assertEqual(text, "공지 목록")
        self.assertEqual(transfer_bytes, 7)
        self.assertEqual(decoded_bytes, len("공지 목록".encode("euc-kr")))


if __name__ == "__main__":
    unittest.main()
