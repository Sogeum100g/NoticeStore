from urllib import robotparser
from urllib.parse import urlparse

import requests

from dataController.security.url_safety import (
    UnsafeUrlError,
    safe_request,
    validate_public_url,
)


def can_fetch(url, user_agent="*"):
    try:
        validated = validate_public_url(url)
    except UnsafeUrlError:
        return False

    parsed_url = urlparse(validated.url)
    robots_url = f"{parsed_url.scheme}://{parsed_url.netloc}/robots.txt"

    rp = robotparser.RobotFileParser()
    try:
        rp.set_url(robots_url)
        response = safe_request(
            requests.Session(),
            "GET",
            robots_url,
            timeout=8,
            max_redirects=3,
            max_response_bytes=256_000,
        )
        response.encoding = response.apparent_encoding or "utf-8"
        rp.parse(response.text.splitlines())
        response.close()
    except Exception:
        return False
    return rp.can_fetch(user_agent, validated.url)
