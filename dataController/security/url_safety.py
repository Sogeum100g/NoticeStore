import ipaddress
import socket
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, Optional, Sequence
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests


ALLOWED_SCHEMES = frozenset({"http", "https"})
ALLOWED_PORTS = frozenset({80, 443})
REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})
SENSITIVE_HEADER_NAMES = frozenset(
    {
        "authorization",
        "cookie",
        "proxy-authorization",
        "x-api-key",
        "x-csrf-token",
        "x-xsrf-token",
        "csrf-token",
    }
)


class UnsafeUrlError(ValueError):
    """Raised when a URL is unsafe for server-side crawler access."""


class ResponseTooLargeError(ValueError):
    """Raised when a crawler response exceeds the configured byte limit."""


@dataclass(frozen=True)
class ValidatedUrl:
    url: str
    hostname: str
    port: int
    addresses: tuple[str, ...]


def _is_public_address(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return (
        ip.is_global
        and not ip.is_private
        and not ip.is_loopback
        and not ip.is_link_local
        and not ip.is_multicast
        and not ip.is_reserved
        and not ip.is_unspecified
    )


def _resolved_addresses(
    hostname: str,
    port: int,
    *,
    resolver: Callable[..., Sequence[tuple]] = socket.getaddrinfo,
) -> tuple[str, ...]:
    try:
        results = resolver(
            hostname,
            port,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
        )
    except (socket.gaierror, OSError) as exc:
        raise UnsafeUrlError(f"호스트 DNS 조회에 실패했습니다: {hostname}") from exc

    addresses = tuple(sorted({item[4][0].split("%", 1)[0] for item in results}))
    if not addresses:
        raise UnsafeUrlError(f"호스트의 A/AAAA 주소가 없습니다: {hostname}")
    if any(not _is_public_address(address) for address in addresses):
        raise UnsafeUrlError("public IP가 아닌 DNS 결과가 포함되어 있습니다.")
    return addresses


def validate_public_url(
    url: str,
    *,
    resolver: Callable[..., Sequence[tuple]] = socket.getaddrinfo,
    allowed_ports: Iterable[int] = ALLOWED_PORTS,
) -> ValidatedUrl:
    if not isinstance(url, str) or not url.strip():
        raise UnsafeUrlError("URL이 비어 있습니다.")
    if any(ord(char) < 32 for char in url):
        raise UnsafeUrlError("URL에 제어 문자가 포함되어 있습니다.")

    try:
        parsed = urlsplit(url.strip())
        port = parsed.port
    except ValueError as exc:
        raise UnsafeUrlError("URL 형식 또는 포트가 올바르지 않습니다.") from exc

    scheme = parsed.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise UnsafeUrlError("http와 https URL만 허용됩니다.")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeUrlError("userinfo가 포함된 URL은 허용되지 않습니다.")
    if not parsed.hostname:
        raise UnsafeUrlError("URL 호스트가 없습니다.")

    effective_port = port or (443 if scheme == "https" else 80)
    if effective_port not in set(allowed_ports):
        raise UnsafeUrlError(f"허용되지 않은 포트입니다: {effective_port}")

    hostname = parsed.hostname.rstrip(".").lower()
    if not hostname:
        raise UnsafeUrlError("URL 호스트가 없습니다.")

    try:
        literal_ip = ipaddress.ip_address(hostname.split("%", 1)[0])
    except ValueError:
        addresses = _resolved_addresses(
            hostname,
            effective_port,
            resolver=resolver,
        )
    else:
        if not _is_public_address(str(literal_ip)):
            raise UnsafeUrlError("public IP가 아닌 주소는 허용되지 않습니다.")
        addresses = (str(literal_ip),)

    normalized = urlunsplit(
        (
            scheme,
            parsed.netloc,
            parsed.path or "/",
            parsed.query,
            "",
        )
    )
    return ValidatedUrl(
        url=normalized,
        hostname=hostname,
        port=effective_port,
        addresses=addresses,
    )


def sanitize_outbound_headers(headers: Optional[Dict[str, str]]) -> Dict[str, str]:
    sanitized: Dict[str, str] = {}
    for key, value in (headers or {}).items():
        if key.lower().strip() in SENSITIVE_HEADER_NAMES:
            continue
        sanitized[str(key)] = str(value)
    return sanitized


def _response_peer_address(response: requests.Response) -> Optional[str]:
    raw = getattr(response, "raw", None)
    socket_candidates = (
        getattr(getattr(raw, "_connection", None), "sock", None),
        getattr(
            getattr(
                getattr(
                    getattr(raw, "_fp", None),
                    "fp",
                    None,
                ),
                "raw",
                None,
            ),
            "_sock",
            None,
        ),
    )
    for connected_socket in socket_candidates:
        if connected_socket is None:
            continue
        try:
            return str(connected_socket.getpeername()[0]).split("%", 1)[0]
        except (AttributeError, OSError, TypeError):
            continue
    return None


def _validate_connected_peer(
    response: requests.Response,
    validated: ValidatedUrl,
) -> None:
    peer = _response_peer_address(response)
    if peer is None:
        return
    if not _is_public_address(peer):
        response.close()
        raise UnsafeUrlError("연결된 peer가 public IP가 아닙니다.")
    expected = set(getattr(validated, "addresses", ()) or ())
    if expected and peer not in expected:
        response.close()
        raise UnsafeUrlError("DNS 검증 결과와 실제 연결 peer가 일치하지 않습니다.")


def safe_request(
    session: requests.Session,
    method: str,
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    params=None,
    json=None,
    data=None,
    timeout: float = 15,
    max_redirects: int = 5,
    max_response_bytes: int = 700_000,
    validator: Callable[[str], ValidatedUrl] = validate_public_url,
) -> requests.Response:
    """Perform a bounded request while validating every redirect hop."""
    current_url = url
    current_method = method.upper()
    current_json = json
    current_data = data
    clean_headers = sanitize_outbound_headers(headers)
    session.trust_env = False

    for redirect_count in range(max_redirects + 1):
        validated = validator(current_url)
        response = session.request(
            current_method,
            validated.url,
            headers=clean_headers,
            params=params if redirect_count == 0 else None,
            json=current_json,
            data=current_data,
            timeout=timeout,
            allow_redirects=False,
            stream=True,
        )
        _validate_connected_peer(response, validated)

        if response.status_code in REDIRECT_STATUS_CODES:
            location = response.headers.get("Location")
            response.close()
            if not location:
                raise UnsafeUrlError("리다이렉트 응답에 Location 헤더가 없습니다.")
            if redirect_count >= max_redirects:
                raise UnsafeUrlError("허용된 리다이렉트 횟수를 초과했습니다.")
            current_url = urljoin(validated.url, location)
            if response.status_code == 303 or (
                response.status_code in {301, 302} and current_method == "POST"
            ):
                current_method = "GET"
                current_json = None
                current_data = None
            continue

        declared_length = response.headers.get("Content-Length")
        if declared_length and current_method != "HEAD":
            try:
                if int(declared_length) > max_response_bytes:
                    response.close()
                    raise ResponseTooLargeError("응답 크기 제한을 초과했습니다.")
            except ValueError:
                pass

        content = bytearray()
        if current_method != "HEAD":
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                content.extend(chunk)
                if len(content) > max_response_bytes:
                    response.close()
                    raise ResponseTooLargeError("응답 크기 제한을 초과했습니다.")
        response._content = bytes(content)
        response._content_consumed = True
        response.url = validated.url
        return response

    raise UnsafeUrlError("안전한 최종 URL을 확인하지 못했습니다.")
