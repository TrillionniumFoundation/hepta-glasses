"""Lexical no-follow and transaction-wide identity policy for evidence reads.

A resolved pathname is not a custody boundary: resolving first follows symbolic
links and lets different reads in one validation transaction observe different
ordinary directory generations. This policy keeps canonical lexical names,
rejects every symbolic-link component, pins ancestor directory identities
across the whole validation snapshot, and requires the visible final name to
still identify the opened file after reading.
"""

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

_DIRECTORY_SNAPSHOT: ContextVar[
    dict[Path, tuple[int, int, int]] | None
] = ContextVar(
    "hepta_external_evidence_directory_snapshot",
    default=None,
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


def _absolute_directory_paths(target: Path) -> tuple[Path, ...]:
    absolute = Path(os.path.abspath(os.fspath(target)))
    current = Path(absolute.anchor)
    paths: list[Path] = []
    for index, component in enumerate(absolute.parts):
        if index:
            current /= component
        paths.append(current)
    return tuple(paths)


def _pin_directories(
    target: Path,
    identities: tuple[tuple[int, int, int], ...],
    *,
    core: ModuleType,
    label: str,
) -> None:
    snapshot = _DIRECTORY_SNAPSHOT.get()
    if snapshot is None:
        return
    paths = _absolute_directory_paths(target)
    if len(paths) != len(identities):
        core.fail(f"{label} directory identity snapshot has the wrong depth")
    for path, identity in zip(paths, identities, strict=True):
        previous = snapshot.setdefault(path, identity)
        if previous != identity:
            core.fail(
                f"{label} directory object changed during the validation "
                f"transaction: {path}"
            )


def install_lexical_scope_policy(core: ModuleType) -> None:
    """Replace resolve-first reads with lexical, no-follow transaction reads."""

    base_validation_snapshot = core.validation_snapshot
    cache_snapshot_bytes = core._cache_snapshot_bytes

    def validation_snapshot(function: Any) -> Any:
        base_wrapped = base_validation_snapshot(function)

        @functools.wraps(function)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            if _DIRECTORY_SNAPSHOT.get() is not None:
                return base_wrapped(*args, **kwargs)
            token = _DIRECTORY_SNAPSHOT.set({})
            try:
                return base_wrapped(*args, **kwargs)
            finally:
                _DIRECTORY_SNAPSHOT.reset(token)

        return wrapped

    def stable_read_target(
        target: Path,
        *,
        label: str,
        maximum: int,
    ) -> bytes:
        if not isinstance(maximum, int) or maximum < 0:
            core.fail(f"{label} has an invalid byte bound")
        lexical = Path(os.path.abspath(os.fspath(target)))
        directory_identities, file_identity = (
            core._capture_absolute_regular_identity(
                lexical,
                label=label,
                fail=core.fail,
            )
        )
        parent = lexical.parent
        _pin_directories(
            parent,
            directory_identities,
            core=core,
            label=label,
        )
        descriptor = core._open_absolute_regular_nofollow(
            lexical,
            label=label,
            fail=core.fail,
            expected_directory_identities=directory_identities,
            expected_file_identity=file_identity,
        )
        try:
            before = os.fstat(descriptor)
            if _regular_identity(before) != file_identity:
                core.fail(f"{label} file identity changed before read")
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
        if _regular_identity(after) != file_identity or len(data) != before.st_size:
            core.fail(f"{label} changed while it was being read")

        final_directories, final_file = core._capture_absolute_regular_identity(
            lexical,
            label=f"{label}.post_read",
            fail=core.fail,
        )
        if final_directories != directory_identities:
            core.fail(f"{label} ancestor directory changed during read")
        if final_file != file_identity:
            core.fail(f"{label} visible name no longer identifies the opened file")
        _pin_directories(
            parent,
            final_directories,
            core=core,
            label=label,
        )
        return data

    def validate_directory(
        target: Path,
        *,
        label: str,
    ) -> tuple[Path, tuple[tuple[int, int, int], ...]]:
        lexical = Path(os.path.abspath(os.fspath(target)))
        identities = core._capture_absolute_directory_identity(
            lexical,
            label=label,
            fail=core.fail,
        )
        _pin_directories(
            lexical,
            identities,
            core=core,
            label=label,
        )
        descriptor = core._open_absolute_directory_nofollow(
            lexical,
            label=label,
            fail=core.fail,
            expected_identities=identities,
        )
        os.close(descriptor)
        final = core._capture_absolute_directory_identity(
            lexical,
            label=f"{label}.post_open",
            fail=core.fail,
        )
        if final != identities:
            core.fail(f"{label} directory changed during validation")
        _pin_directories(
            lexical,
            final,
            core=core,
            label=label,
        )
        return lexical, identities

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

        lexical_root, _ = validate_directory(
            root,
            label=f"{label}.scope_root",
        )
        lexical_path = lexical_root / Path(*relative.parts)
        try:
            lexical_path.relative_to(lexical_root)
        except ValueError:
            core.fail(f"{label} escapes its lexical scope")

        # Require every parent component to exist as a real no-follow directory.
        validate_directory(
            lexical_path.parent,
            label=f"{label}.parent",
        )

        try:
            os.stat(lexical_path, follow_symlinks=False)
        except FileNotFoundError:
            return lexical_path
        except OSError as error:
            core.fail(f"{label} cannot inspect its lexical target: {error}")

        cache = core._READ_SNAPSHOT.get()
        if cache is not None and lexical_path in cache:
            data = cache[lexical_path]
            if len(data) > maximum:
                core.fail(f"{label} exceeds the {maximum}-byte validation bound")
            return lexical_path

        data = stable_read_target(
            lexical_path,
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
        data = stable_read_target(
            lexical_path,
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
        public_key_data = read_bounded_file(
            public_key,
            label=label,
            maximum=core.MAX_PUBLIC_KEY_BYTES,
        )
        with tempfile.TemporaryDirectory(
            prefix="hepta-evidence-spki-"
        ) as directory:
            snapshot = Path(directory) / "public.pem"
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
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

    core.validation_snapshot = validation_snapshot
    core._stable_read_target = stable_read_target
    core._safe_scoped_path = safe_scoped_path
    core.safe_artifact_path = safe_artifact_path
    core.safe_key_path = safe_key_path
    core._read_bounded_file = read_bounded_file
    core._normalized_public_key_digest = normalized_public_key_digest
    core._DIRECTORY_SNAPSHOT = _DIRECTORY_SNAPSHOT


__all__ = ["install_lexical_scope_policy"]
