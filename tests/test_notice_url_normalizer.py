import unittest

from dataController.scraper.deterministic_extractor import (
    extract_notices_deterministically,
)
from dataController.scraper.notice_url_normalizer import (
    canonicalize_notice_detail_url,
)


class NoticeUrlNormalizerTests(unittest.TestCase):
    def test_tracking_fragment_and_query_order_are_normalized(self):
        result = canonicalize_notice_detail_url(
            "HTTPS://Example.COM:443/notices/1/?b=2&utm_source=x&a=1#top"
        )
        self.assertEqual(result, "https://example.com/notices/1/?a=1&b=2")

    def test_redirect_wrapper_is_unwrapped(self):
        result = canonicalize_notice_detail_url(
            "https://events.example/cs/a/0?url="
            "https%3A%2F%2Fevents.example%2Fevent%2F42%3Fref%3Dmail"
        )
        self.assertEqual(
            result,
            "https://events.example/event/42?ref=mail",
        )

    def test_notice_view_route_aliases_share_one_identity(self):
        raw = """
        <table><tbody>
          <tr><td><a href="/News/Notice/NoticeViews/123">동일 공지</a></td>
              <td>2026.08.28</td></tr>
          <tr><td><a href="/News/Notice/Views/123">동일 공지</a></td>
              <td>2026.08.28</td></tr>
        </tbody></table>
        """
        result = extract_notices_deterministically(
            raw,
            content_type="text/html",
            base_url="https://game.example/News/Notice",
        )

        self.assertEqual(len(result.notices), 1)
        self.assertEqual(
            result.notices[0]["detail_url"],
            "https://game.example/News/Notice/views/123",
        )


if __name__ == "__main__":
    unittest.main()
