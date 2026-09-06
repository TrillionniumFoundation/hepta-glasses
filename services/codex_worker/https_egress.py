"""Exact-domain HTTPS broker primitive for a separately isolated worker.

The broker resolves one allowlisted hostname under a bounded helper process,
rejects every non-global answer, connects to the selected numeric address while
retaining the original hostname for TLS verification, sends one HTTP/1.1 request,
and never follows redirects. It is not network isolation: an arbitrary child
must be placed in an OS sandbox that cannot open sockets except through this
trusted broker.
"""
from __future__ import annotations

import http.client
import ipaddress
import json
import re
import socket
import ssl
import subprocess
import time
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping
from urllib.parse import urlsplit

_DOMAIN = re.compile(
    r"(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z"
)
_METHODS = frozenset({"GET", "POST"})
_CRITICAL_HEADERS = frozenset(
    {"content-length", "transfer-encoding", "location", "content-encoding", "upgrade"}
)
_RESOLVER = r'''import json,socket,sys
host=sys.argv[1]
rows=[]
for family,kind,proto,canon,sockaddr in socket.getaddrinfo(host,443,type=socket.SOCK_STREAM):
    if family not in (socket.AF_INET,socket.AF_INET6): continue
    rows.append([family,sockaddr[0]])
rows=sorted(set(map(tuple,rows)))
if not rows or len(rows)>32: raise SystemExit(2)
sys.stdout.write(json.dumps(rows,separators=(",",":")))
'''


class EgressError(RuntimeError):
    """Stable broker error that does not embed resolver/server-controlled text."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class EgressPolicy:
    domains: tuple[str, ...]
    timeout_seconds: float = 10.0
    maximum_request_bytes: int = 1024 * 1024
    maximum_response_bytes: int = 4 * 1024 * 1024
    maximum_response_headers: int = 64
    maximum_response_header_bytes: int = 32768

    def __post_init__(self) -> None:
        if (
            type(self.domains) is not tuple
            or not 1 <= len(self.domains) <= 64
            or any(type(value) is not str or not _DOMAIN.fullmatch(value) for value in self.domains)
            or tuple(sorted(set(self.domains))) != self.domains
        ):
            raise EgressError("egress_domains_invalid")
        for value in self.domains:
            try:
                ipaddress.ip_address(value)
            except ValueError:
                pass
            else:
                raise EgressError("egress_domains_invalid")
        if type(self.timeout_seconds) not in (int, float) or not 0.1 <= float(self.timeout_seconds) <= 60:
            raise EgressError("egress_timeout_invalid")
        integer_limits = (
            (self.maximum_request_bytes, 0, 16 * 1024 * 1024, "egress_request_limit_invalid"),
            (self.maximum_response_bytes, 1, 64 * 1024 * 1024, "egress_response_limit_invalid"),
            (self.maximum_response_headers, 1, 256, "egress_header_limit_invalid"),
            (self.maximum_response_header_bytes, 1024, 256 * 1024, "egress_header_limit_invalid"),
        )
        for value, lower, upper, code in integer_limits:
            if type(value) is not int or not lower <= value <= upper:
                raise EgressError(code)


@dataclass(frozen=True)
class EgressResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes

    def __post_init__(self) -> None:
        object.__setattr__(self, "headers", MappingProxyType(dict(self.headers)))


@dataclass(frozen=True)
class _Address:
    family: int
    value: str


def _remaining(deadline: float, code: str = "egress_timeout") -> float:
    value = deadline - time.monotonic()
    if value <= 0:
        raise EgressError(code)
    return value


def _request_target(url: str, domains: tuple[str, ...]) -> tuple[str, str]:
    if type(url) is not str or not 1 <= len(url) <= 8192 or any(ord(ch) < 32 for ch in url):
        raise EgressError("egress_url_invalid")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise EgressError("egress_url_invalid") from None
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.fragment
        or port not in (None, 443)
    ):
        raise EgressError("egress_url_invalid")
    host = parts.hostname
    if host not in domains or parts.netloc not in (host, host + ":443"):
        raise EgressError("egress_domain_denied")
    target = (parts.path or "/") + (("?" + parts.query) if parts.query else "")
    try:
        target.encode("ascii")
    except UnicodeEncodeError:
        raise EgressError("egress_target_invalid") from None
    if len(target) > 4096 or not target.startswith("/") or "\\" in target or " " in target:
        raise EgressError("egress_target_invalid")
    lowered = target.lower()
    if "%0d" in lowered or "%0a" in lowered:
        raise EgressError("egress_target_invalid")
    index = 0
    while True:
        index = target.find("%", index)
        if index < 0:
            break
        if index + 2 >= len(target) or not re.fullmatch(r"[0-9A-F]{2}", target[index + 1:index + 3]):
            raise EgressError("egress_target_invalid")
        index += 3
    return host, target


def _validate_addresses(rows: object) -> tuple[_Address, ...]:
    if type(rows) is not list or not 1 <= len(rows) <= 32:
        raise EgressError("egress_dns_unavailable")
    result: list[_Address, ...] = []
    seen: set[tuple[int, str]] = set()
    for row in rows:
        if type(row) is not list or len(row) != 2 or type(row[0]) is not int or type(row[1]) is not str:
            raise EgressError("egress_dns_unavailable")
        family, value = row
        if family not in (socket.AF_INET, socket.AF_INET6) or "%" in value:
            raise EgressError("egress_dns_address_rejected")
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            raise EgressError("egress_dns_address_rejected") from None
        if not address.is_global or address.is_multicast or address.is_unspecified:
            raise EgressError("egress_dns_address_rejected")
        canonical = address.compressed
        key = (family, canonical)
        if key not in seen:
            seen.add(key)
            result.append(_Address(family, canonical))
    if not result:
        raise EgressError("egress_dns_unavailable")
    return tuple(sorted(result, key=lambda item: (item.family, item.value)))


def _resolve_addresses(host: str, timeout_seconds: float) -> tuple[_Address, ...]:
    try:
        completed = subprocess.run(
            ["/proc/self/exe", "-I", "-S", "-c", _RESOLVER, host],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout_seconds,
            check=False,
            env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
         )
    except (OSError, subprocess.SubprocessError):
        raise EgressError("egress_dns_unavailable") from None
    if completed.returncode != 0 or len(completed.stdout) > 16384:
        raise EgressError("egress_dns_unavailable")
    try:
        rows = json.loads(completed.stdout.decode("ascii"))
    except (UnicodeError, ValueError):
        raise EgressError("egress_dns_unavailable") from None
    return _validate_addresses(rows)


def _connect_tls(address: _Address, host: str, timeout_seconds: float) -> ssl.SSLSocket:
    raw = socket.socket(address.family, socket.SOCK_STREAM)
    try:
        raw.settimeout(timeout_seconds)
        destination = (address.value, 443) if address.family == socket.AF_INET else (address.value, 443, 0, 0)
        raw.connect(destination)
        context = ssl.create_default_context(purpose=ssl.Purpose.SERVER_AUTH)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        wrapped = context.wrap_socket(raw, server_hostname=host)
        wrapped.settimeout(timeout_seconds)
        return wrapped
    except (OSError, ssl.SSLError):
        raw.close()
        raise


class ExactDomainHttpsBroker:
    """Perform one bounded HTTPS request under an immutable exact-domain policy."""

    def __init__(self, policy: EgressPolicy):
        if not isinstance(policy, EgressPolicy):
            raise EgressError("egress_policy_invalid")
        self._policy = policy

    @property
    def policy(self) -> EgressPolicy:
        return self._policy

    def request(self, url: str, *, method: str = "GET", body: bytes = b"") -> EgressResponse:
        if type(method) is not str or method not in _METHODS:
            raise EgressError("egress_method_denied")
        if type(body) is not bytes or len(body) > self._policy.maximum_request_bytes or (method == "GET" and body):
            raise EgressError("egress_request_invalid")
        host, target = _request_target(url, self._policy.domains)
        deadline = time.monotonic() + float(self._policy.timeout_seconds)
        addresses = _resolve_addresses(host, _remaining(deadline))
        connection = None
        for address in addresses:
            try:
                connection = _connect_tls(address, host, _remaining(deadline))
                break
            except (OSError, ssl.SSLError):
                continue
        if connection is None:
            raise EgressError("egress_connect_failed")
        response: http.client.HTTPResponse | None = None
        try:
            content_headers = b""
            if body:
                content_headers = b"Content-Type: application/octet-stream\r\n"
            request = (
                f"{method} {target} HTTP/1.1\r\n"
                f"Host: {host}\r\n"
                "User-Agent: hepta-exact-egress/1\r\n"
                "Accept: application/octet-stream\r\n"
                "Accept-Encoding: identity\r\n"
                "Connection: close\r\n"
                f"Content-Length: {len(body)}\r\n"
            ).encode("ascii") + content_headers + b"\r\n" + body
            connection.settimeout(_remaining(deadline))
            connection.sendall(request)
            connection.settimeout(_remaining(deadline))
            response = http.client.HTTPResponse(connection, method=method)
            response.begin()
            headers = response.getheaders()
            if len(headers) > self._policy.maximum_response_headers:
                raise EgressError("egress_response_headers_invalid")
            total = 0
            normalized: dict[str, str] = {}
            counts: dict[str, int] = {}
            for raw_name, raw_value in headers:
                name = raw_name.lower()
                if (
                    not re.fullmatch(r"[a-z0-9!#$%&'*+.^_`|~-]+", name)
                    or any(ord(ch) < 32 and ch != "\t" for ch in raw_value)
                    or "\r" in raw_value
                    or "\n" in raw_value
                ):
                    raise EgressError("egress_response_headers_invalid")
                total += len(name.encode("ascii")) + len(raw_value.encode("latin-1"))
                if total > self._policy.maximum_response_header_bytes:
                    raise EgressError("egress_response_headers_invalid")
                counts[name] = counts.get(name, 0) + 1
                if name in _CRITICAL_HEADERG and counts[name] != 1:
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
                if int(declared) > self._policy.maximum_response_bytes:
                    raise EgressError("egress_response_too_large")
            output = bytearray()
            while True:
                connection.settimeout(_remaining(deadline))
                chunk = response.read(min(65536, self._policy.maximum_response_bytes + 1 - len(output)))
                if not chunk:
                    break
                output.extend(chunk)
                if len(output) > self._policy.maximum_response_bytes:
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
