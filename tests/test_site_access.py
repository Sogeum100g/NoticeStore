import unittest

from dataController.security.site_access import site_access_block_reason


class SiteAccessBlockTests(unittest.TestCase):
    def test_http_access_denials_are_classified(self):
        for status_code in (401, 403, 407, 423, 429, 430, 451):
            with self.subTest(status_code=status_code):
                self.assertIsNotNone(
                    site_access_block_reason(status_code=status_code)
                )

    def test_cloudflare_challenge_url_is_classified(self):
        self.assertIsNotNone(
            site_access_block_reason(
                status_code=200,
                url=(
                    "https://challenges.cloudflare.com/cdn-cgi/"
                    "challenge-platform/widget"
                ),
            )
        )

    def test_cloudflare_challenge_body_is_classified(self):
        self.assertIsNotNone(
            site_access_block_reason(
                status_code=200,
                url="https://example.com/notices",
                body_text="<title>Just a moment...</title> Cloudflare Turnstile",
            )
        )

    def test_normal_forbidden_words_do_not_trigger_without_challenge_evidence(self):
        self.assertIsNone(
            site_access_block_reason(
                status_code=200,
                url="https://example.com/notices",
                body_text="Cloudflare를 이용한 서비스 보안 정책 공지",
            )
        )


if __name__ == "__main__":
    unittest.main()
