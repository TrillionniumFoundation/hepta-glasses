"""Exact-domain HTTPS broker for a separately OS-isolated worker.

This is a capability primitive, not network isolation: untrusted code must be
unable to open sockets directly and reach this broker only through trusted IPC.
"""
from __future__ import annotations

import ssl
import time

from .https_egress_dns import Address, connect_tls, request_target, resolve_addresses
from .https_egress_http import exchange, remaining
from .https_egress_types import EgressError, EgressPolicy, EgressResponse, METHODS

__all__ = ["EgressError", "EgressPolicy", "EgressResponse", "ExactDomainHttpsBroker"]


class ExactDomainHttpsBroker:
    """Perform one bounded request under an immutable exact-domain policy."""

    def __init__(self, policy: EgressPolicy):
        if not isinstance(policy, EgressPolicy):
            raise EgressError("egress_policy_invalid")
        self._policy = policy

    @property
    def policy(self) -> EgressPolicy:
        return self._policy

    def request(self, url: str, *, method: str = "GET", body: bytes = b"") -> EgressResponse:
        if type(method) is not str or method not in METHODS:
            raise EgressError("egress_method_denied")
        if (type(body) is not bytes or len(body) > self._policy.maximum_request_bytes
                or (method == "GET" and body)):
            raise EgressError("egress_request_invalid")
        host, target = request_target(url, self._policy.domains)
        deadline = time.monotonic() + float(self._policy.timeout_seconds)
        addresses = resolve_addresses(host, remaining(deadline))
        connection = None
        for address in addresses:
            try:
                connection = connect_tls(address, host, remaining(deadline))
                break
            except (OSError, ssl.SSLError):
                continue
        if connection is None:
            raise EgressError("egress_connect_failed")
        return exchange(connection, host=host, target=target, method=method,
                        body=body, policy=self._policy, deadline=deadline)
