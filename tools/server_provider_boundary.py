"""Exact-byte cloud provider declarations inside the existing source scanner.

No source directory is exempt. Only two named marker categories in two fixed
cloud files may be declared; credential material and bypass patterns still fail.
This source policy is not external approval or a runtime authorization boundary.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from types import MappingProxyType
from typing import Mapping

CONTRACT = "contracts/server-provider-boundary-v1.json"
_PROVIDER = "services/model_gateway/responses_provider.py"
_TEST = "services/model_gateway/test_responses_provider.py"
_SLOTS = {
    _PROVIDER: ("cloud_transport", {"direct provider endpoint": frozenset({"api.openai.com"})}),
    _TEST: ("wire_regression", {
        "direct provider endpoint": frozenset({"api.openai.com"}),
        "provider key name": frozenset({"OPENAI_API_KEY"}),
    }),
}
_MODULE = "services.model_gateway.responses_provider"


def _fail(code: str) -> None:
    raise AssertionError(code)


def read_regular(root: Path, relative: str, *, maximum_bytes: int = 8 * 1024 * 1024) -> bytes:
    """Read one regular repository file; reject links and changed read identity.

    Exact declarations are checked against these same bytes, never a second
    pathname read. The checkout and its parent remain a trusted CI host input.
    """
    path = PurePosixPath(relative)
    if (not relative or path.is_absolute() or "\\" in relative
            or any(part in {"", ".", ".."} for part in relative.split("/"))):
        _fail("provider_boundary_path_invalid")
    current = root
    try:
        if root.is_symlink() or not root.is_dir():
            _fail("provider_boundary_root_invalid")
        for part in path.parts[:-1]:
            current /= part
            if not stat.S_ISDIR(current.lstat().st_mode):
                _fail("provider_boundary_link_or_directory_invalid")
        current /= path.name
        before = current.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_size > maximum_bytes:
            _fail("provider_boundary_file_invalid")
        with current.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            data = stream.read(maximum_bytes + 1)
            after = os.fstat(stream.fileno())
        def identity(value):
            return (value.st_dev, value.st_ino, value.st_mode, value.st_size,
                    value.st_mtime_ns, value.st_ctime_ns)
        if (len(data) > maximum_bytes or len(data) != before.st_size
                or identity(before) != identity(opened) or identity(opened) != identity(after)
                or identity(after) != identity(current.lstat())):
            _fail("provider_boundary_read_changed")
        return data
    except (OSError, ValueError):
        raise AssertionError("provider_boundary_source_unavailable") from None


def _pairs(values):
    result = {}
    for key, value in values:
        if key in result:
            _fail("provider_boundary_duplicate_field")
        result[key] = value
    return result


def _import_violation(relative: str, text: str) -> bool:
    # Static direct-import fence, not a claim to detect dynamic/reflection imports.
    if not relative.endswith(".py") or relative.startswith("services/model_gateway/"):
        return False
    try:
        parsed = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        _fail("provider_boundary_python_parse_failed")
    package = list(PurePosixPath(relative).parts[:-1])
    for node in ast.walk(parsed):
        modules = []
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            prefix = node.module or ""
            if node.level:
                if node.level > len(package):
                    continue  # Invalid import is not permission to load the provider.
                prefix = ".".join(package[:len(package) - node.level + 1]
                                  + ([prefix] if prefix else []))
            modules = [prefix, *(prefix + "." + alias.name for alias in node.names)]
            if prefix == "services.model_gateway" and any(a.name == "*" for a in node.names):
                return True
        if any(m == _MODULE or m.startswith(_MODULE + ".") for m in modules):
            return True
    return False


class ServerProviderBoundary:
    """A source declaration can narrow a fixed marker slot, never create new slots."""
    def __init__(self, root: Path):
        try:
            document = json.loads(read_regular(root, CONTRACT, maximum_bytes=8192).decode("utf-8"),
                                  object_pairs_hook=_pairs)
        except (ValueError, UnicodeError, RecursionError):
            raise AssertionError("provider_boundary_contract_invalid") from None
        if (type(document) is not dict or set(document) != {"schema_version", "contract_id", "entries"}
                or type(document["schema_version"]) is not int or document["schema_version"] != 1
                or document["contract_id"] != "server-provider-boundary-v1"
                or type(document["entries"]) is not list or len(document["entries"]) != len(_SLOTS)):
            _fail("provider_boundary_contract_invalid")
        hashes = {}
        for row in document["entries"]:
            if type(row) is not dict or set(row) != {"path", "sha256", "role"}:
                _fail("provider_boundary_entry_invalid")
            path = row["path"]
            if (type(path) is not str or path not in _SLOTS or path in hashes
                    or row["role"] != _SLOTS[path][0] or type(row["sha256"]) is not str
                    or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"])):
                _fail("provider_boundary_entry_invalid")
            hashes[path] = row["sha256"]
        if set(hashes) != set(_SLOTS):
            _fail("provider_boundary_incomplete")
        self.hashes = MappingProxyType(hashes)
        self.seen: set[str] = set()

    def inspect(self, relative: str, raw: bytes, patterns: Mapping[str, re.Pattern]) -> list[str]:
        if type(raw) is not bytes:
            _fail("provider_boundary_snapshot_invalid")
        try:
            text = raw.decode("utf-8")
        except UnicodeError:
            raise AssertionError("provider_boundary_encoding_invalid") from None
        allowed = {}
        if relative in self.hashes:
            if relative in self.seen:
                _fail("provider_boundary_duplicate_source")
            if hashlib.sha256(raw).hexdigest() != self.hashes[relative]:
                _fail(f"provider_boundary_source_digest_mismatch: {relative}")
            self.seen.add(relative)
            allowed = _SLOTS[relative][1]
        violations = []
        for label, pattern in patterns.items():
            if any(match.group(0) not in allowed.get(label, ()) for match in pattern.finditer(text)):
                violations.append(f"{label}: {relative}")
        if _import_violation(relative, text):
            violations.append(f"cloud provider direct import outside model service: {relative}")
        return violations

    def finish(self) -> None:
        if self.seen != set(self.hashes):
            _fail("provider_boundary_declared_source_not_scanned")
