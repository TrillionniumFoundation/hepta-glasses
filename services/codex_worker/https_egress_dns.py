"""Bounded DNS, request-target and numeric-address TLS custody."""
from __future__ import annotations

import ipaddress
import json
import re
import socket
import ssl
import subprocess
from dataclasses import dataclass
from urllib.parse import urlsplit

from .https_egress_types import EgressError

RESOLVER = r'''import json,socket,sys
host=sys.argv[1]
rows=[]
for family,kind,proto,canon,sockaddr in socket.getaddrinfo(host,443,type=socket.SOCK_STREAM):
    if family not in (socket.AF_INET,socket.AF_INET6): continue
    rows.append([family,sockaddr[0]])
rows=sorted(set(map(tuple,rows)))
if not rows or len(rows)>32: raise SystemExit(2)
sys.stdout.write(json.dumps(rows,separators=(",",":")))
'''


@dataclass(frozen=True)
class Address:
    family: int
    value: str


def request_target(url: str, domains: tuple[str, ...]) -> tuple[str, str]:
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


def validate_addresses(rows: object) -> tuple[Address, ...]:
    if type(rows) is not list or not 1 <= len(rows) <= 32:
        raise EgressError("egress_dns_unavailable")
    result: list[Address] = []
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
        key = (family, address.compressed)
        if key not in seen:
            seen.add(key)
            result.append(Address(*key))
    if not result:
        raise EgressError("egress_dns_unavailable")
    return tuple(sorted(result, key=lambda item: (item.family, item.value)))


def resolve_addresses(host: str, timeout_seconds: float) -> tuple[Address, ...]:
    try:
        completed = subprocess.run(
            ["/proc/self/exe", "-I", "-S", "-c", RESOLVER, host],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=timeout_seconds, check=False,
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
    return validate_addresses(rows)


def connect_tls(address: Address, host: str, timeout_seconds: float) -> ssl.SSLSocket:
    raw = socket.socket(address.family, socket.SOCK_STREAM)
    try:
        raw.settimeout(timeout_seconds)
        destination = ((address.value, 443) if address.family == socket.AF_INET
                       else (address.value, 443, 0, 0))
        raw.connect(destination)
        context = ssl.create_default_context(purpose=ssl.Purpose.SERVER_AUTH)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        wrapped = context.wrap_socket(raw, server_hostname=host)
        wrapped.settimeout(timeout_seconds)
        return wrapped
    except (OSError, ssl.SSLError):
        raw.close()
        raise
