"""Descriptor-anchored discovery of committed accepted evidence envelopes."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .core import fail
from .snapshot_io import _open_absolute_directory_nofollow

MAX_DISCOVERY_FILE_BYTES = 16 * 1024 * 1024
MAX_DISCOVERY_TOTAL_BYTES = 256 * 1024 * 1024
MAX_DISCOVERY_ENTRIES = 100_000
MAX_DISCOVERY_DEPTH = 64
_CANONICAL_CONTRACT_ID = "hepta-external-evidence-envelope-v1"


@dataclass(frozen=True)
class DiscoveredAcceptedEnvelope:
    path: Path
    document: dict[str, Any]
    sha256: str


def _identity(status: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        status.st_dev,
        status.st_ino,
        status.st_mode,
        status.st_size,
        status.st_mtime_ns,
        status.st_ctime_ns,
    )


def _directory_flags() -> int:
    if not hasattr(os, "O_DIRECTORY") or not hasattr(os, "O_NOFOLLOW"):
        fail("platform cannot securely discover committed evidence")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    return flags


def _file_flags() -> int:
    if not hasattr(os, "O_NOFOLLOW"):
        fail("platform cannot securely discover committed evidence")
    flags = os.O_RDONLY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    return flags


def _read_regular_at(
    parent_fd: int,
    name: str,
    *,
    label: str,
) -> tuple[bytes, os.stat_result]:
    try:
        lexical_before = os.stat(
            name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
    except OSError as error:
        fail(f"{label} cannot be inspected safely: {error}")
    if not stat.S_ISREG(lexical_before.st_mode):
        fail(f"{label} must remain a regular file")
    if lexical_before.st_size > MAX_DISCOVERY_FILE_BYTES:
        fail(f"{label} exceeds the discovery file-size bound")

    try:
        descriptor = os.open(name, _file_flags(), dir_fd=parent_fd)
    except OSError as error:
        fail(f"{label} cannot be opened safely: {error}")
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            fail(f"{label} opened as a non-regular object")
        if _identity(opened) != _identity(lexical_before):
            fail(f"{label} changed between lexical inspection and open")

        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(
                descriptor,
                min(1024 * 1024, MAX_DISCOVERY_FILE_BYTES + 1 - total),
            )
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_DISCOVERY_FILE_BYTES:
                fail(f"{label} exceeds the discovery file-size bound")
        opened_after = os.fstat(descriptor)
        payload = b"".join(chunks)
        if _identity(opened_after) != _identity(opened):
            fail(f"{label} changed while being read")
        if len(payload) != opened.st_size:
            fail(f"{label} produced an unstable byte count")

        try:
            lexical_after = os.stat(
                name,
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
        except OSError as error:
            fail(f"{label} disappeared after read: {error}")
        if _identity(lexical_after) != _identity(opened):
            fail(f"{label} name no longer identifies the opened file")
        return payload, opened
    finally:
        os.close(descriptor)


def _parse_object(payload: bytes) -> dict[str, Any] | None:
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON number: {value}")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON member: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(
            payload.decode("utf-8"),
            parse_constant=reject_constant,
            object_pairs_hook=reject_duplicates,
        )
    except (UnicodeError, ValueError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def discover_accepted_envelopes(base: Path) -> list[DiscoveredAcceptedEnvelope]:
    """Recursively discover accepted envelopes without following mutable names.

    The lexical root and every child directory are opened through no-follow
    directory descriptors. Lexical, opened, post-traversal, and final-name
    identities must agree. Any symbolic link, special object, ordinary
    replacement, unstable read, or resource-bound violation at or below the
    evidence root fails the repository gate instead of being ignored as a
    possible hidden package.
    """

    lexical_base = Path(os.path.abspath(os.fspath(base)))
    try:
        root_lexical_before = os.lstat(lexical_base)
    except OSError as error:
        fail(f"committed evidence root is unavailable: {error}")
    if not stat.S_ISDIR(root_lexical_before.st_mode):
        fail("committed evidence root must be a real directory, not a link or special object")

    root_fd = _open_absolute_directory_nofollow(
        lexical_base,
        label="committed evidence root",
        fail=fail,
    )
    root_opened = os.fstat(root_fd)
    if not stat.S_ISDIR(root_opened.st_mode):
        os.close(root_fd)
        fail("committed evidence root must be a directory")
    if _identity(root_opened) != _identity(root_lexical_before):
        os.close(root_fd)
        fail("committed evidence root changed between lexical inspection and open")

    results: list[DiscoveredAcceptedEnvelope] = []
    entry_count = 0
    total_bytes = 0

    def walk(directory_fd: int, relative: Path, depth: int) -> None:
        nonlocal entry_count, total_bytes
        if depth > MAX_DISCOVERY_DEPTH:
            fail("committed evidence tree exceeds the discovery depth bound")
        directory_before = os.fstat(directory_fd)
        try:
            with os.scandir(directory_fd) as iterator:
                names = sorted(entry.name for entry in iterator)
        except OSError as error:
            fail(f"committed evidence directory cannot be listed safely: {error}")

        for name in names:
            if name in {"", ".", ".."} or "/" in name or "\x00" in name:
                fail("committed evidence tree contains an invalid entry name")
            entry_count += 1
            if entry_count > MAX_DISCOVERY_ENTRIES:
                fail("committed evidence tree exceeds the entry-count bound")
            label = f"committed evidence entry {(relative / name).as_posix()}"
            try:
                lexical_before = os.stat(
                    name,
                    dir_fd=directory_fd,
                    follow_symlinks=False,
                )
            except OSError as error:
                fail(f"{label} cannot be inspected safely: {error}")

            if stat.S_ISLNK(lexical_before.st_mode):
                fail(f"{label} is a symbolic link")
            if stat.S_ISDIR(lexical_before.st_mode):
                try:
                    child_fd = os.open(
                        name,
                        _directory_flags(),
                        dir_fd=directory_fd,
                    )
                except OSError as error:
                    fail(f"{label} cannot be opened as a stable directory: {error}")
                try:
                    child_opened = os.fstat(child_fd)
                    if _identity(child_opened) != _identity(lexical_before):
                        fail(f"{label} changed between inspection and open")
                    walk(child_fd, relative / name, depth + 1)
                    child_after = os.fstat(child_fd)
                    if _identity(child_after) != _identity(child_opened):
                        fail(f"{label} changed during traversal")
                    try:
                        lexical_after = os.stat(
                            name,
                            dir_fd=directory_fd,
                            follow_symlinks=False,
                        )
                    except OSError as error:
                        fail(f"{label} disappeared after traversal: {error}")
                    if _identity(lexical_after) != _identity(child_opened):
                        fail(f"{label} name no longer identifies the traversed directory")
                finally:
                    os.close(child_fd)
                continue
            if not stat.S_ISREG(lexical_before.st_mode):
                fail(f"{label} is not a regular file or directory")

            payload, _ = _read_regular_at(
                directory_fd,
                name,
                label=label,
            )
            total_bytes += len(payload)
            if total_bytes > MAX_DISCOVERY_TOTAL_BYTES:
                fail("committed evidence tree exceeds the aggregate byte bound")
            document = _parse_object(payload)
            if document is None:
                continue
            acceptance = document.get("acceptance")
            if (
                document.get("contract_id") == _CANONICAL_CONTRACT_ID
                and isinstance(acceptance, dict)
                and acceptance.get("state") == "accepted"
            ):
                results.append(
                    DiscoveredAcceptedEnvelope(
                        path=lexical_base / relative / name,
                        document=document,
                        sha256=hashlib.sha256(payload).hexdigest(),
                    )
                )

        directory_after = os.fstat(directory_fd)
        if _identity(directory_after) != _identity(directory_before):
            fail("committed evidence directory changed during traversal")

    try:
        walk(root_fd, Path(), 0)
        root_after = os.fstat(root_fd)
        if _identity(root_after) != _identity(root_opened):
            fail("committed evidence root changed during traversal")
        try:
            root_lexical_after = os.lstat(lexical_base)
        except OSError as error:
            fail(f"committed evidence root disappeared after traversal: {error}")
        if _identity(root_lexical_after) != _identity(root_opened):
            fail("committed evidence root name no longer identifies the traversed directory")
    finally:
        os.close(root_fd)
    return results
