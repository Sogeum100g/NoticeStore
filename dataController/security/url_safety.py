import ipaddress
import logging
import os
import socket
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, Mapping, Optional, Sequence
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests


logger = logging.getLogger(__name__)

ALLOWED_SCHEMES = frozenset({"http", "https"})
ALLOWED_PORTS = frozenset({80, 443})
REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})
DEFAULT_MAX_TRANSFER_BYTES = 5 * 1024 * 1024
DEFAULT_MAX_DECODED_BYTES = 5 * 1024 * 1024
MAX_CONFIGURABLE_RESPONSE_BYTES = 64 * 1024 * 1024
TRANSFER_LIMIT_ENV = "CRAWLER_MAX_TRANSFER_BYTES"
DECODED_LIMIT_ENV = "CRAWLER_MAX_DECODED_BYTES"
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
    """Raised with bounded response metadata when a size limit is exceeded."""

    def __init__(
        self,
        *,
        limit_kind: str,
        observed_bytes: int,
        limit_bytes: int,
        content_type: str = "",
        content_encoding: str = "",
    ) -> None:
        self.limit_kind = limit_kind
        self.observed_bytes = observed_bytes
        self.limit_bytes = limit_bytes
        self.content_type = content_type or "unknown"
        self.content_encoding = content_encoding or "identity"
        super().__init__(
            "응답 크기 제한을 초과했습니다. "
            f"kind={self.limit_kind}, "
            f"observed_bytes={self.observed_bytes}, "
            f"limit_bytes={self.limit_bytes}, "
            f"content_type={self.content_type}, "
            f"content_encoding={self.content_encoding}"
        )


@dataclass(frozen=True)
class ResponseLimitPolicy:
    max_transfer_bytes: int
    max_decoded_bytes: int


@dataclass(frozen=True)
class ResponseSizeMetrics:
    transfer_bytes: int
    decoded_bytes: int
    content_type: str
    content_encoding: str


def _configured_byte_limit(
    environ: Mapping[str, str],
    name: str,
    default: int,
) -> int:
    raw_value = environ.get(name)
    if raw_value is None or not raw_value.strip():
        return default
    try:
        value = int(raw_value)
    except ValueError:
        logger.warning("%s 값이 정수가 아니어서 기본값 %d를 사용합니다.", name, default)
        return default
    if value <= 0 or value > MAX_CONFIGURABLE_RESPONSE_BYTES:
        logger.warning(
            "%s 값은 1~%d bytes 범위여야 하므로 기본값 %d를 사용합니다.",
            name,
            MAX_CONFIGURABLE_RESPONSE_BYTES,
            default,
        )
        return default
    return value


def load_response_limit_policy(
    environ: Optional[Mapping[str, str]] = None,
) -> ResponseLimitPolicy:
    """Load finite crawler response limits from the process environment."""
    source = os.environ if environ is None else environ
    return ResponseLimitPolicy(
        max_transfer_bytes=_configured_byte_limit(
            source,
            TRANSFER_LIMIT_ENV,
            DEFAULT_MAX_TRANSFER_BYTES,
        ),
        max_decoded_bytes=_configured_byte_limit(
            source,
            DECODED_LIMIT_ENV,
            DEFAULT_MAX_DECODED_BYTES,
        ),
    )


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


def _bounded_header_value(value: Optional[str], fallback: str) -> str:
    compact = " ".join(str(value or "").split())[:160]
    return compact or fallback


def _response_metadata(response: requests.Response) -> tuple[str, str]:
    return (
        _bounded_header_value(response.headers.get("Content-Type"), "unknown"),
        _bounded_header_value(response.headers.get("Content-Encoding"), "identity"),
    )


def _raw_transfer_bytes(response: requests.Response) -> Optional[int]:
    raw = getattr(response, "raw", None)
    if raw is None:
        return None
    try:
        value = raw.tell()
    except (AttributeError, OSError, TypeError, ValueError):
        value = getattr(raw, "_fp_bytes_read", None)
    try:
        return max(0, int(value)) if value is not None else None
    except (TypeError, ValueError):
        return None


def _response_too_large(
    response: requests.Response,
    *,
    limit_kind: str,
    observed_bytes: int,
    limit_bytes: int,
) -> ResponseTooLargeError:
    content_type, content_encoding = _response_metadata(response)
    response.close()
    return ResponseTooLargeError(
        limit_kind=limit_kind,
        observed_bytes=observed_bytes,
        limit_bytes=limit_bytes,
        content_type=content_type,
        content_encoding=content_encoding,
    )


def _append_decoded_chunk(
    response: requests.Response,
    content: bytearray,
    chunk: bytes,
    decoded_limit: int,
) -> None:
    if len(content) + len(chunk) > decoded_limit:
        raise _response_too_large(
            response,
            limit_kind="decoded_streamed",
            observed_bytes=len(content) + len(chunk),
            limit_bytes=decoded_limit,
        )
    content.extend(chunk)


def _decoder_output(decoder, data: bytes, remaining: int) -> bytes:
    try:
        return decoder.decompress(data, max_length=max(remaining + 1, 1))
    except TypeError:  # urllib3 1.x decoder compatibility
        return decoder.decompress(data)


def _read_bounded_content(
    response: requests.Response,
    *,
    transfer_limit: int,
    decoded_limit: int,
) -> tuple[bytes, int]:
    """Count encoded bytes and bound decoder output before buffering it."""
    content = bytearray()
    transfer_bytes = 0
    raw = getattr(response, "raw", None)
    can_decode_raw = bool(
        raw is not None
        and hasattr(raw, "stream")
        and hasattr(raw, "_init_decoder")
    )

    if can_decode_raw:
        raw._init_decoder()
        decoder = getattr(raw, "_decoder", None)
        for encoded_chunk in raw.stream(
            amt=64 * 1024,
            decode_content=False,
        ):
            if not encoded_chunk:
                continue
            transfer_bytes += len(encoded_chunk)
            if transfer_bytes > transfer_limit:
                raise _response_too_large(
                    response,
                    limit_kind="transfer_streamed",
                    observed_bytes=transfer_bytes,
                    limit_bytes=transfer_limit,
                )
            decoded_chunk = (
                _decoder_output(
                    decoder,
                    encoded_chunk,
                    decoded_limit - len(content),
                )
                if decoder is not None
                else encoded_chunk
            )
            _append_decoded_chunk(
                response,
                content,
                decoded_chunk,
                decoded_limit,
            )

        while decoder is not None and getattr(
            decoder,
            "has_unconsumed_tail",
            False,
        ):
            previous_length = len(content)
            decoded_chunk = _decoder_output(
                decoder,
                b"",
                decoded_limit - len(content),
            )
            _append_decoded_chunk(
                response,
                content,
                decoded_chunk,
                decoded_limit,
            )
            if len(content) == previous_length:
                break
        if decoder is not None:
            _append_decoded_chunk(
                response,
                content,
                decoder.flush(),
                decoded_limit,
            )
        return bytes(content), transfer_bytes

    raw_transfer_available = _raw_transfer_bytes(response) is not None
    for decoded_chunk in response.iter_content(chunk_size=64 * 1024):
        if not decoded_chunk:
            continue
        observed_transfer = _raw_transfer_bytes(response)
        if observed_transfer is not None:
            transfer_bytes = max(transfer_bytes, observed_transfer)
        elif response.headers.get("Content-Encoding", "identity").lower() in {
            "",
            "identity",
        }:
            transfer_bytes += len(decoded_chunk)
        if transfer_bytes > transfer_limit:
            raise _response_too_large(
                response,
                limit_kind="transfer_streamed",
                observed_bytes=transfer_bytes,
                limit_bytes=transfer_limit,
            )
        _append_decoded_chunk(
            response,
            content,
            decoded_chunk,
            decoded_limit,
        )
    if not raw_transfer_available:
        declared_length = response.headers.get("Content-Length")
        if declared_length:
            try:
                transfer_bytes = int(declared_length)
            except ValueError:
                pass
    return bytes(content), transfer_bytes


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
    max_response_bytes: Optional[int] = None,
    max_transfer_bytes: Optional[int] = None,
    limit_policy: Optional[ResponseLimitPolicy] = None,
    validator: Callable[[str], ValidatedUrl] = validate_public_url,
    read_body: bool = True,
) -> requests.Response:
    """Perform a bounded request while validating every redirect hop."""
    policy = limit_policy or load_response_limit_policy()
    decoded_limit = (
        max_response_bytes
        if max_response_bytes is not None
        else policy.max_decoded_bytes
    )
    transfer_limit = (
        max_transfer_bytes
        if max_transfer_bytes is not None
        else (
            max_response_bytes
            if max_response_bytes is not None
            else policy.max_transfer_bytes
        )
    )
    if decoded_limit <= 0 or transfer_limit <= 0:
        raise ValueError("응답 크기 제한은 0보다 커야 합니다.")

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

        skip_body = current_method == "HEAD" or not read_body

        declared_length = response.headers.get("Content-Length")
        if declared_length and not skip_body:
            try:
                declared_bytes = int(declared_length)
            except ValueError:
                declared_bytes = None
            if declared_bytes is not None and declared_bytes > transfer_limit:
                raise _response_too_large(
                    response,
                    limit_kind="transfer_declared",
                    observed_bytes=declared_bytes,
                    limit_bytes=transfer_limit,
                )

        content = b""
        transfer_bytes = 0
        if not skip_body:
            content, transfer_bytes = _read_bounded_content(
                response,
                transfer_limit=transfer_limit,
                decoded_limit=decoded_limit,
            )
        elif current_method != "HEAD":
            response.close()
        content_type, content_encoding = _response_metadata(response)
        response._response_size_metrics = ResponseSizeMetrics(
            transfer_bytes=transfer_bytes,
            decoded_bytes=len(content),
            content_type=content_type,
            content_encoding=content_encoding,
        )
        response._content = content
        response._content_consumed = True
        response.url = validated.url
        return response

    raise UnsafeUrlError("안전한 최종 URL을 확인하지 못했습니다.")
