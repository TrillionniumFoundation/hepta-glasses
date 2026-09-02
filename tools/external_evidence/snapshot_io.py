"""Immutable lexical-path snapshot I/O for external evidence validation."""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path, PurePosixPath
from types import ModuleType


def _require_secure_path_api(fail: object) -> None:
    required_flags = ("O_DIRECTORY", "O_NOFOLLOW")
    if any(not hasattr(os, name) for name in required_flags):
        fail("platform cannot securely open external-evidence paths")
    supports_dir_fd = getattr(os, "supports_dir_fd", set())
    if os.open not in supports_dir_fd:
        fail("platform lacks directory-descriptor support for evidence paths")


def _directory_flags() -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    return flags


def _open_absolute_directory_nofollow(
    target: Path,
    *,
    label: str,
    fail: object,
) -> int:
    """Open one resolved absolute directory without following raced ancestors."""

    _require_secure_path_api(fail)
    absolute = Path(os.path.abspath(os.fspath(target)))
    if not absolute.is_absolute() or not absolute.parts:
        fail(f"{label} must be an absolute directory path")

    opened: list[int] = []
    try:
        current = os.open(absolute.anchor, _directory_flags())
        opened.append(current)
        for component in absolute.parts[1:]:
            try:
                current = os.open(
                    component,
                    _directory_flags(),
                    dir_fd=current,
                )
            except OSError as error:
                fail(
                    f"{label} contains an unsafe or replaced directory "
                    f"component {component!r}: {error}"
                )
            opened.append(current)
        result = opened.pop()
    finally:
        for descriptor in reversed(opened):
            os.close(descriptor)
    return result


def _open_absolute_regular_nofollow(
    target: Path,
    *,
    label: str,
    fail: object,
) -> int:
    """Open one resolved absolute file while rejecting symlinked ancestors."""

    _require_secure_path_api(fail)
    absolute = Path(os.path.abspath(os.fspath(target)))
    if not absolute.is_absolute() or len(absolute.parts) < 2:
        fail(f"{label} must be an absolute file path")

    parent = Path(absolute.anchor, *absolute.parts[1:-1])
    parent_fd = _open_absolute_directory_nofollow(
        parent,
        label=f"{label}.parent",
        fail=fail,
    )
    flags = os.O_RDONLY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        try:
            descriptor = os.open(
                absolute.name,
                flags,
                dir_fd=parent_fd,
            )
        except OSError as error:
            fail(f"{label} cannot be opened safely: {error}")
    finally:
        os.close(parent_fd)
    return descriptor


def install_snapshot_io(core: ModuleType) -> None:
    """Install fail-closed snapshot functions into the core validation module.

    Validation identity is the normalized lexical input path. Resolution is
    used only to establish the first in-scope target. The resolved absolute
    target is then opened from the filesystem anchor with directory-relative,
    no-follow traversal, so an ancestor replaced after ``resolve`` cannot
    redirect the read outside its checked scope. Retargeting the original URI
    later in the same validation cannot expose different bytes either.
    """

    def stable_read_target(
        target: Path,
        *,
        label: str,
        maximum: int,
    ) -> bytes:
        descriptor = _open_absolute_regular_nofollow(
            target,
            label=label,
            fail=core.fail,
        )
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
        return data

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

        try:
            resolved_root = root.resolve(strict=True)
        except OSError as error:
            core.fail(f"{label} scope root is unavailable: {error}")
        lexical_path = resolved_root / Path(*relative.parts)

        existing_target: Path | None
        try:
            existing_target = lexical_path.resolve(strict=True)
            resolved_target = existing_target
        except FileNotFoundError:
            existing_target = None
            resolved_target = lexical_path.resolve(strict=False)
        except OSError as error:
            core.fail(f"{label} cannot be resolved safely: {error}")
        try:
            resolved_target.relative_to(resolved_root)
        except ValueError:
            core.fail(f"{label} escapes its scope")

        # Selecting an existing scoped URI is the first security-relevant read.
        # Pin its stable bytes immediately under the lexical path identity. The
        # resolved target is opened with no-follow traversal from the filesystem
        # anchor, so a raced ancestor replacement fails rather than redirecting.
        cache = core._READ_SNAPSHOT.get()
        if (
            cache is not None
            and lexical_path not in cache
            and existing_target is not None
        ):
            cache[lexical_path] = stable_read_target(
                existing_target,
                label=label,
                maximum=core.MAX_ARTIFACT_BYTES,
            )
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

        data = stable_read_target(
            resolved_target,
            label=label,
            maximum=maximum,
        )
        if cache is not None:
            cache[lexical_path] = data
        return data

    core._open_absolute_directory_nofollow = _open_absolute_directory_nofollow
    core._stable_read_target = stable_read_target
    core._safe_scoped_path = safe_scoped_path
    core._read_bounded_file = read_bounded_file
