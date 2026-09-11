
"""Immutable lexical-path snapshot I/O for external evidence validation."""

from __future__ import annotations

import functools
import hashlib
import os
import re
import stat
import tempfile
from contextvars import ContextVar
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import Any

MAX_SNAPSHOT_BYTES = 512 * 1024 * 1024
_SNAPSHOT_TOTAL_BYTES: ContextVar[int | None] = ContextVar(
    "hepta_external_evidence_snapshot_total_bytes",
    default=None,
)


def _require_secure_path_api(fail: Any) -> None:
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


def _directory_identity(value: os.stat_result) -> tuple[int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        stat.S_IFMT(value.st_mode),
    )


def _regular_identity(
    value: os.stat_result,
) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        stat.S_IFMT(value.st_mode),
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _capture_absolute_directory_identity(
    target: Path,
    *,
    label: str,
    fail: Any,
) -> tuple[tuple[int, int, int], ...]:
    """Capture every directory object selected by one absolute lexical path."""

    _require_secure_path_api(fail)
    absolute = Path(os.path.abspath(os.fspath(target)))
    if not absolute.is_absolute() or not absolute.parts:
        fail(f"{label} must be an absolute directory path")

    identities: list[tuple[int, int, int]] = []
    current = Path(absolute.anchor)
    try:
        for index, component in enumerate(absolute.parts):
            if index:
                current /= component
            state = os.stat(current, follow_symlinks=False)
            if not stat.S_ISDIR(state.st_mode):
                fail(
                    f"{label} contains a non-directory or symbolic-link "
                    f"component: {component!r}"
                )
            identities.append(_directory_identity(state))
    except OSError as error:
        fail(f"{label} cannot snapshot its directory identity: {error}")
    return tuple(identities)


def _capture_absolute_regular_identity(
    target: Path,
    *,
    label: str,
    fail: Any,
) -> tuple[
    tuple[tuple[int, int, int], ...],
    tuple[int, int, int, int, int, int],
]:
    """Capture the exact resolved ancestor and file identities selected for reading."""

    _require_secure_path_api(fail)
    absolute = Path(os.path.abspath(os.fspath(target)))
    if not absolute.is_absolute() or len(absolute.parts) < 2:
        fail(f"{label} must be an absolute file path")

    parent = Path(absolute.anchor, *absolute.parts[1:-1])
    directory_identities = _capture_absolute_directory_identity(
        parent,
        label=f"{label}.parent",
        fail=fail,
    )
    try:
        file_state = os.stat(absolute, follow_symlinks=False)
    except OSError as error:
        fail(f"{label} cannot snapshot its file identity: {error}")
    if not stat.S_ISREG(file_state.st_mode):
        fail(f"{label} must reference a regular file")
    return directory_identities, _regular_identity(file_state)


def _open_absolute_directory_nofollow(
    target: Path,
    *,
    label: str,
    fail: Any,
    expected_identities: tuple[tuple[int, int, int], ...] | None = None,
) -> int:
    """Open one absolute directory and require every ancestor identity to match."""

    _require_secure_path_api(fail)
    absolute = Path(os.path.abspath(os.fspath(target)))
    if not absolute.is_absolute() or not absolute.parts:
        fail(f"{label} must be an absolute directory path")
    if expected_identities is not None and len(expected_identities) != len(
        absolute.parts
    ):
        fail(f"{label} identity snapshot has the wrong depth")

    opened: list[int] = []
    try:
        current = os.open(absolute.anchor, _directory_flags())
        opened.append(current)
        opened_state = os.fstat(current)
        if not stat.S_ISDIR(opened_state.st_mode):
            fail(f"{label} anchor is not a directory")
        if (
            expected_identities is not None
            and _directory_identity(opened_state) != expected_identities[0]
        ):
            fail(f"{label} directory identity changed before open")

        for index, component in enumerate(absolute.parts[1:], start=1):
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
            opened_state = os.fstat(current)
            if not stat.S_ISDIR(opened_state.st_mode):
                fail(f"{label} component {component!r} is not a directory")
            if (
                expected_identities is not None
                and _directory_identity(opened_state) != expected_identities[index]
            ):
                fail(
                    f"{label} directory identity changed before open: "
                    f"{component!r}"
                )
        result = opened.pop()
    finally:
        for descriptor in reversed(opened):
            os.close(descriptor)
    return result


def _open_absolute_regular_nofollow(
    target: Path,
    *,
    label: str,
    fail: Any,
    expected_directory_identities: (
        tuple[tuple[int, int, int], ...] | None
    ) = None,
    expected_file_identity: (
        tuple[int, int, int, int, int, int] | None
    ) = None,
) -> int:
    """Open one resolved file and require the captured object identities to match."""

    _require_secure_path_api(fail)
    absolute = Path(os.path.abspath(os.fspath(target)))
    if not absolute.is_absolute() or len(absolute.parts) < 2:
        fail(f"{label} must be an absolute file path")

    parent = Path(absolute.anchor, *absolute.parts[1:-1])
    parent_fd = _open_absolute_directory_nofollow(
        parent,
        label=f"{label}.parent",
        fail=fail,
        expected_identities=expected_directory_identities,
    )
    flags = os.O_RDONLY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    descriptor: int | None = None
    try:
        try:
            descriptor = os.open(
                absolute.name,
                flags,
                dir_fd=parent_fd,
            )
        except OSError as error:
            fail(f"{label} cannot be opened safely: {error}")
        opened_state = os.fstat(descriptor)
        if not stat.S_ISREG(opened_state.st_mode):
            fail(f"{label} must reference a regular file")
        if (
            expected_file_identity is not None
            and _regular_identity(opened_state) != expected_file_identity
        ):
            fail(f"{label} file identity changed before open")
        result = descriptor
        descriptor = None
        return result
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(parent_fd)


def install_snapshot_io(core: ModuleType) -> None:
    """Install fail-closed, transaction-bounded snapshot functions into ``core``."""

    def validation_snapshot(function: Any) -> Any:
        @functools.wraps(function)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            if core._READ_SNAPSHOT.get() is not None:
                return function(*args, **kwargs)
            cache_token = core._READ_SNAPSHOT.set({})
            total_token = _SNAPSHOT_TOTAL_BYTES.set(0)
            try:
                return function(*args, **kwargs)
            finally:
                _SNAPSHOT_TOTAL_BYTES.reset(total_token)
                core._READ_SNAPSHOT.reset(cache_token)

        return wrapped

    def cache_snapshot_bytes(path: Path, data: bytes, *, label: str) -> None:
        cache = core._READ_SNAPSHOT.get()
        if cache is None:
            return
        if path in cache:
            return
        total = _SNAPSHOT_TOTAL_BYTES.get()
        if total is None:
            core.fail(f"{label} snapshot accounting is unavailable")
        next_total = total + len(data)
        if next_total > MAX_SNAPSHOT_BYTES:
            core.fail(
                "external-evidence validation snapshot exceeds the "
                f"{MAX_SNAPSHOT_BYTES}-byte transaction bound"
            )
        cache[path] = data
        _SNAPSHOT_TOTAL_BYTES.set(next_total)

    def stable_read_target(
        target: Path,
        *,
        label: str,
        maximum: int,
    ) -> bytes:
        if not isinstance(maximum, int) or maximum < 0:
            core.fail(f"{label} has an invalid byte bound")
        directory_identities, file_identity = _capture_absolute_regular_identity(
            target,
            label=label,
            fail=core.fail,
        )
        descriptor = _open_absolute_regular_nofollow(
            target,
            label=label,
            fail=core.fail,
            expected_directory_identities=directory_identities,
            expected_file_identity=file_identity,
        )
        try:
            before = os.fstat(descriptor)
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
                    core.fail(f"{label} exceeds the {maximum}-byte validation bound")
            after = os.fstat(descriptor)
        except OSError as error:
            core.fail(f"{label} cannot be read stably: {error}")
        finally:
            os.close(descriptor)

        data = b"".join(chunks)
        if _regular_identity(before) != _regular_identity(after) or len(data) != before.st_size:
            core.fail(f"{label} changed while it was being read")
        return data

    def safe_scoped_path(
        root: Path,
        uri: str,
        *,
        pattern: re.Pattern[str],
        scheme: str,
        label: str,
        maximum: int | None = None,
    ) -> Path:
        match = pattern.fullmatch(uri)
        if match is None:
            core.fail(f"{label} must use {scheme}:// with a scoped relative path")
        raw_relative = match.group(1)
        relative = PurePosixPath(raw_relative)
        if (
            relative.is_absolute()
            or any(part in {"", ".", ".."} for part in relative.parts)
            or relative.as_posix() != raw_relative
        ):
            core.fail(f"{label} must use a canonical scoped relative path")

        if maximum is None:
            if scheme == "key":
                maximum = core.MAX_PUBLIC_KEY_BYTES
            elif "signature" in label.casefold():
                maximum = core.MAX_SIGNATURE_BYTES
            else:
                maximum = core.MAX_ARTIFACT_BYTES
        if not isinstance(maximum, int) or maximum < 0:
            core.fail(f"{label} has an invalid byte bound")

        try:
            resolved_root = root.resolve(strict=True)
        except OSError as error:
            core.fail(f"{label} scope root is unavailable: {error}")
        if not resolved_root.is_dir():
            core.fail(f"{label} scope root must be a directory")
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

        cache = core._READ_SNAPSHOT.get()
        if cache is not None and lexical_path not in cache and existing_target is not None:
            data = stable_read_target(
                existing_target,
                label=label,
                maximum=maximum,
            )
            cache_snapshot_bytes(lexical_path, data, label=label)
        return lexical_path

    def safe_artifact_path(
        root: Path,
        uri: str,
        *,
        label: str,
        maximum: int | None = None,
    ) -> Path:
        return safe_scoped_path(
            root,
            uri,
            pattern=core.ARTIFACT_URI,
            scheme="artifact",
            label=label,
            maximum=maximum,
        )

    def safe_key_path(
        root: Path,
        uri: str,
        *,
        label: str,
        maximum: int | None = None,
    ) -> Path:
        return safe_scoped_path(
            root,
            uri,
            pattern=core.KEY_URI,
            scheme="key",
            label=label,
            maximum=(
                core.MAX_PUBLIC_KEY_BYTES if maximum is None else maximum
            ),
        )

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
        cache_snapshot_bytes(lexical_path, data, label=label)
        return data

    def normalized_public_key_digest(
        public_key: Path,
        *,
        openssl_binary: str,
        label: str,
    ) -> str:
        """Normalize the exact pinned key bytes, never a re-resolved pathname."""

        public_key_data = read_bounded_file(
            public_key,
            label=label,
            maximum=core.MAX_PUBLIC_KEY_BYTES,
        )
        with tempfile.TemporaryDirectory(
            prefix="hepta-evidence-spki-"
        ) as directory:
            snapshot = Path(directory) / "public.pem"
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            if hasattr(os, "O_CLOEXEC"):
                flags |= os.O_CLOEXEC
            descriptor = os.open(snapshot, flags, 0o600)
            try:
                remaining = memoryview(public_key_data)
                while remaining:
                    written = os.write(descriptor, remaining)
                    if written <= 0:
                        core.fail(f"{label} public-key snapshot write stalled")
                    remaining = remaining[written:]
                os.fsync(descriptor)
            except OSError as error:
                core.fail(f"{label} public-key snapshot could not be written: {error}")
            finally:
                os.close(descriptor)

            der = core._run_openssl(
                [
                    core._resolve_openssl(openssl_binary),
                    "pkey",
                    "-pubin",
                    "-in",
                    str(snapshot),
                    "-pubout",
                    "-outform",
                    "DER",
                ],
                label=label,
            )
        if (
            len(der) != core.ED25519_SPKI_BYTES
            or not der.startswith(core.ED25519_SPKI_PREFIX)
        ):
            core.fail(f"{label} must contain an actual Ed25519 public key")
        return hashlib.sha256(der).hexdigest()

    core.MAX_SNAPSHOT_BYTES = MAX_SNAPSHOT_BYTES
    core.validation_snapshot = validation_snapshot
    core._cache_snapshot_bytes = cache_snapshot_bytes
    core._capture_absolute_directory_identity = _capture_absolute_directory_identity
    core._capture_absolute_regular_identity = _capture_absolute_regular_identity
    core._open_absolute_directory_nofollow = _open_absolute_directory_nofollow
    core._open_absolute_regular_nofollow = _open_absolute_regular_nofollow
    core._stable_read_target = stable_read_target
    core._safe_scoped_path = safe_scoped_path
    core.safe_artifact_path = safe_artifact_path
    core.safe_key_path = safe_key_path
    core._read_bounded_file = read_bounded_file
    core._normalized_public_key_digest = normalized_public_key_digest
