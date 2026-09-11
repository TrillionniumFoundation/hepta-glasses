"""Immutable types for the exact-domain HTTPS broker."""
from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

DOMAIN = re.compile(
    r"(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z"
)
METHODS = frozenset({"GET", "POST"})
CRITICAL_HEADERS = frozenset(
    {"content-length", "transfer-encoding", "location", "content-encoding", "upgrade"}
)


class EgressError(RuntimeError):
    """Stable broker error that never embeds resolver/server-controlled text."""

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
            or any(type(value) is not str or not DOMAIN.fullmatch(value) for value in self.domains)
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
        limits = (
            (self.maximum_request_bytes, 0, 16 * 1024 * 1024, "egress_request_limit_invalid"),
            (self.maximum_response_bytes, 1, 64 * 1024 * 1024, "egress_response_limit_invalid"),
            (self.maximum_response_headers, 1, 256, "egress_header_limit_invalid"),
            (self.maximum_response_header_bytes, 1024, 256 * 1024, "egress_header_limit_invalid"),
        )
        for value, lower, upper, code in limits:
            if type(value) is not int or not lower <= value <= upper:
                raise EgressError(code)


@dataclass(frozen=True)
class EgressResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes

    def __post_init__(self) -> None:
        object.__setattr__(self, "headers", MappingProxyType(dict(self.headers)))
