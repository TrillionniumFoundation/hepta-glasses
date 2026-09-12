"""One-shot bounded HTTP/1.1 exchange for an already verified TLS socket."""
from __future__ import annotations

import http.client
import re
import ssl
import time

from .https_egress_types import CRITICAL_HEADERS, EgressError, EgressPolicy, EgressResponse


def remaining(deadline: float, code: str = "egress_timeout") -> float:
    value = deadline - time.monotonic()
    if value <= 0:
        raise EgressError(code)
    return value


def exchange(connection, *, host: str, target: str, method: str, body: bytes,
             policy: EgressPolicy, deadline: float) -> EgressResponse:
    response: http.client.HTTPResponse | None = None
    try:
        content_headers = b"Content-Type: application/octet-stream\r\n" if body else b""
        request = (
            f"{method} {target} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            "User-Agent: hepta-exact-egress/1\r\n"
            "Accept: application/octet-stream\r\n"
            "Accept-Encoding: identity\r\n"
            "Connection: close\r\n"
            f"Content-Length: {len(body)}\r\n"
        ).encode("ascii") + content_headers + b"\r\n" + body
        connection.settimeout(remaining(deadline))
        connection.sendall(request)
        connection.settimeout(remaining(deadline))
        response = http.client.HTTPResponse(connection, method=method)
        response.begin()
        headers = response.getheaders()
        if len(headers) > policy.maximum_response_headers:
            raise EgressError("egress_response_headers_invalid")
        total = 0
        normalized: dict[str, str] = {}
        counts: dict[str, int] = {}
        for raw_name, raw_value in headers:
            name = raw_name.lower()
            if (
                not re.fullmatch(r"[a-z0-9!#$%&'*+.^_`|~-]+", name)
                or any(ord(ch) < 32 and ch != "\t" for ch in raw_value)
                or "\r" in raw_value or "\n" in raw_value
            ):
                raise EgressError("egress_response_headers_invalid")
            total += len(name.encode("ascii")) + len(raw_value.encode("latin-1"))
            if total > policy.maximum_response_header_bytes:
                raise EgressError("egress_response_headers_invalid")
            counts[name] = counts.get(name, 0) + 1
            if name in CRITICAL_HEADERS and counts[name] != 1:
                raise EgressError("egress_response_headers_invalid")
            normalized[name] = raw_value.strip()
        if response.status == 101 or 300 <= response.status < 400 or "location" in normalized:
            raise EgressError("egress_redirect_rejected")
        if response.status < 200 or response.status > 599:
            raise EgressError("egress_response_status_invalid")
        if "transfer-encoding" in normalized or "upgrade" in normalized:
            raise EgressError("egress_response_headers_invalid")
        encoding = normalized.get("content-encoding")
        if encoding is not None and encoding.lower() != "identity":
            raise EgressError("egress_compression_rejected")
        declared = normalized.get("content-length")
        if declared is not None:
            if not re.fullmatch(r"0|[1-9][0-9]*", declared):
                raise EgressError("egress_response_headers_invalid")
            if int(declared) > policy.maximum_response_bytes:
                raise EgressError("egress_response_too_large")
        output = bytearray()
        while True:
            connection.settimeout(remaining(deadline))
            chunk = response.read(min(65536, policy.maximum_response_bytes + 1 - len(output)))
            if not chunk:
                break
            output.extend(chunk)
            if len(output) > policy.maximum_response_bytes:
                raise EgressError("egress_response_too_large")
        if declared is not None and len(output) != int(declared):
            raise EgressError("egress_response_truncated")
        return EgressResponse(response.status, normalized, bytes(output))
    except (OSError, ssl.SSLError, http.client.HTTPException, TimeoutError, UnicodeError):
        raise EgressError("egress_transport_failed") from None
    finally:
        if response is not None:
            response.close()
        try:
            connection.close()
        except OSError:
            pass
