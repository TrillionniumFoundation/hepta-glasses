"""Immutable lexical-path snapshot I/O for external evidence validation."""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path, PurePosixPath
from types import ModuleType


def install_snapshot_io(core: ModuleType) -> None:
    """Install fail-closed snapshot functions into the core validation module.

    Validation identity is the normalized lexical input path. Resolution is
    used only to verify scope and safely open the first target. Retargeting a
    symbolic link during the same validation therefore cannot expose different
    bytes to hashing, parsing, secret scanning, or signature verification.
    """

    def safe_scoped_path(
        root: Path,
        uri: str,
        *,
        pattern: re.Pattern[str],
        scheme: str,
        label: str,
    ) -> Path:
        match = pattern.fullmatch(uri)
        if match is None:
            core.fail(f"{label} must use {scheme}:// with a scoped relative path")
        relative = PurePosixPath(match.group(1))
        if relative.is_absolute() or any(
            part in {"", ".", ".."} for part in relative.parts
        ):
            core.fail(f"{label} escapes its scope")

        resolved_root = root.resolve()
        lexical_path = resolved_root / Path(*relative.parts)
        # ``safe_artifact_path`` is also used to select a new detached-signature
        # destination. Resolve existing ancestors and symlinks without requiring
        # the final path to exist; actual reads remain strict in
        # ``read_bounded_file``. This preserves scope checks while allowing an
        # atomically created output below a not-yet-created directory.
        resolved_target = lexical_path.resolve(strict=False)
        try:
            resolved_target.relative_to(resolved_root)
        except ValueError:
            core.fail(f"{label} escapes its scope")
        return lexical_path

    def read_bounded_file(path: Path, *, label: str, maximum: int) -> bytes:
        lexical_path = Path(os.path.abspath(os.fspath(path)))
        cache = core._READ_SNAPSHOT.get()
        if cache is not None and lexical_path in cache:
            data = cache[lexical_path]
            if len(data) > maximum:
                core.fail(f"{label} exceeds the {maximum}-byte validation bound")
            return data

        try:
            resolved_target = lexical_path.resolve(strict=True)
        except OSError as error:
            core.fail(f"{label} references a missing or unreadable file: {error}")

        flags = os.O_RDONLY
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(resolved_target, flags)
        except OSError as error:
            core.fail(f"{label} cannot be opened safely: {error}")
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode):
                core.fail(f"{label} must reference a regular file")
            if before.st_size > maximum:
                core.fail(f"{label} exceeds the {maximum}-byte validation bound")
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = os.read(
                    descriptor,
                    min(1024 * 1024, maximum + 1 - total),
                )
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > maximum:
                    core.fail(
                        f"{label} exceeds the {maximum}-byte validation bound"
                    )
            after = os.fstat(descriptor)
        except OSError as error:
            core.fail(f"{label} cannot be read stably: {error}")
        finally:
            os.close(descriptor)

        identity_before = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        identity_after = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        data = b"".join(chunks)
        if identity_before != identity_after or len(data) != before.st_size:
            core.fail(f"{label} changed while it was being read")
        if cache is not None:
            cache[lexical_path] = data
        return data

    core._safe_scoped_path = safe_scoped_path
    core._read_bounded_file = read_bounded_file
