"""Descriptor-bound input, key, and output custody for evidence signing."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from .core import (
    ARTIFACT_URI,
    ED25519_SPKI_BYTES,
    ED25519_SPKI_PREFIX,
    MAX_JSON_BYTES,
    MAX_PUBLIC_KEY_BYTES,
    MAX_SIGNATURE_BYTES,
    _capture_absolute_directory_identity,
    _capture_absolute_regular_identity,
    _open_absolute_directory_nofollow,
    _open_absolute_regular_nofollow,
    _read_bounded_file,
    _stable_read_target,
    read_object,
    validation_snapshot,
)


class BundleSnapshot:
    def __init__(
        self,
        path: Path,
        value: dict[str, Any],
        raw: bytes,
        directories: tuple[tuple[int, int, int], ...],
        file_identity: tuple[int, int, int, int, int, int],
    ) -> None:
        self.path = path
        self.value = value
        self.raw = raw
        self.sha256 = hashlib.sha256(raw).hexdigest()
        self.directories = directories
        self.file_identity = file_identity


def _fail(message: str) -> None:
    raise ValueError(message)


def _directory_identity(value: os.stat_result) -> tuple[int, int, int]:
    return (value.st_dev, value.st_ino, stat.S_IFMT(value.st_mode))


def _file_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        stat.S_IFMT(value.st_mode),
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _read_fd(descriptor: int, label: str, maximum: int) -> bytes:
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode) or before.st_size > maximum:
        raise ValueError(f"{label} is not a bounded regular file")
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = os.read(descriptor, min(1024 * 1024, maximum + 1 - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > maximum:
            raise ValueError(f"{label} exceeds the {maximum}-byte bound")
    after = os.fstat(descriptor)
    data = b"".join(chunks)
    if _file_identity(before) != _file_identity(after) or len(data) != before.st_size:
        raise ValueError(f"{label} changed while being read")
    return data


@validation_snapshot
def _read_bundle_bytes(path: Path) -> tuple[dict[str, Any], bytes]:
    value = read_object(path, "external evidence bundle")
    raw = _read_bounded_file(
        path,
        label="external evidence bundle",
        maximum=MAX_JSON_BYTES,
    )
    return value, raw


def load_bundle_snapshot(path: Path) -> BundleSnapshot:
    lexical = Path(os.path.abspath(os.fspath(path)))
    value, raw = _read_bundle_bytes(lexical)
    directories, file_identity = _capture_absolute_regular_identity(
        lexical,
        label="external evidence bundle",
        fail=_fail,
    )
    descriptor = _open_absolute_regular_nofollow(
        lexical,
        label="external evidence bundle",
        fail=_fail,
        expected_directory_identities=directories,
        expected_file_identity=file_identity,
    )
    try:
        current = _read_fd(descriptor, "external evidence bundle", MAX_JSON_BYTES)
    finally:
        os.close(descriptor)
    if current != raw:
        raise ValueError("external evidence bundle changed after input snapshot")
    return BundleSnapshot(lexical, value, raw, directories, file_identity)


def read_bundle(path: Path) -> dict[str, Any]:
    return load_bundle_snapshot(path).value


def _write_all(descriptor: int, data: bytes) -> None:
    remaining = memoryview(data)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise OSError("custody write made no progress")
        remaining = remaining[written:]


def _write_private_snapshot(path: Path, data: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    descriptor = os.open(path, flags, 0o600)
    try:
        _write_all(descriptor, data)
        os.fsync(descriptor)
        state = os.fstat(descriptor)
        if (
            not stat.S_ISREG(state.st_mode)
            or state.st_size != len(data)
            or state.st_mode & 0o077
        ):
            raise RuntimeError("private-key snapshot is not one private regular file")
    finally:
        os.close(descriptor)


def read_private_key_snapshot(
    private_key: Path,
    *,
    forbidden_root: Path | None = None,
) -> bytes:
    try:
        resolved = private_key.resolve(strict=True)
    except OSError as error:
        raise ValueError(f"private key is missing or unreadable: {error}") from error
    if forbidden_root is not None:
        try:
            custody = forbidden_root.resolve(strict=True)
        except OSError as error:
            raise ValueError(f"custody root is unavailable: {error}") from error
        try:
            resolved.relative_to(custody)
        except ValueError:
            pass
        else:
            raise ValueError("private key must remain outside evidence custody")
    data = _stable_read_target(
        resolved,
        label="private key",
        maximum=MAX_PUBLIC_KEY_BYTES,
    )
    if b"PRIVATE KEY" not in data:
        raise ValueError("private key file does not contain PEM private-key material")
    return data


def _verify_private_bytes(data: bytes) -> None:
    with tempfile.TemporaryDirectory(prefix="hepta-key-check-") as directory:
        key = Path(directory) / "private.pem"
        _write_private_snapshot(key, data)
        result = subprocess.run(
            ["openssl", "pkey", "-in", str(key), "-pubout", "-outform", "DER"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=15,
            check=False,
        )
    if result.returncode != 0:
        raise ValueError("private key cannot be parsed non-interactively")
    if (
        len(result.stdout) != ED25519_SPKI_BYTES
        or not result.stdout.startswith(ED25519_SPKI_PREFIX)
    ):
        raise ValueError("private key must be an actual Ed25519 private key")


def verify_private_key_ed25519(private_key: Path) -> None:
    _verify_private_bytes(read_private_key_snapshot(private_key))


def sign_ed25519(
    private_key: Path,
    payload: bytes,
    *,
    forbidden_root: Path | None = None,
) -> bytes:
    if not isinstance(payload, bytes):
        raise TypeError("payload must be bytes")
    if forbidden_root is None:
        key_bytes = read_private_key_snapshot(private_key)
    else:
        key_bytes = read_private_key_snapshot(
            private_key,
            forbidden_root=forbidden_root,
        )
    _verify_private_bytes(key_bytes)
    with tempfile.TemporaryDirectory(prefix="hepta-sign-") as directory:
        root = Path(directory)
        key = root / "private.pem"
        message = root / "message.bin"
        signature = root / "signature.bin"
        _write_private_snapshot(key, key_bytes)
        message.write_bytes(payload)
        result = subprocess.run(
            [
                "openssl",
                "pkeyutl",
                "-sign",
                "-inkey",
                str(key),
                "-rawin",
                "-in",
                str(message),
                "-out",
                str(signature),
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=15,
            check=False,
        )
        if result.returncode != 0 or not signature.is_file():
            raise RuntimeError("OpenSSL Ed25519 signing failed")
        signed = _stable_read_target(
            signature.resolve(strict=True),
            label="generated signature",
            maximum=MAX_SIGNATURE_BYTES,
        )
    if len(signed) != 64:
        raise RuntimeError("OpenSSL produced a non-Ed25519 signature")
    return signed


def _require_output_api() -> None:
    if any(not hasattr(os, item) for item in ("O_DIRECTORY", "O_NOFOLLOW")):
        raise ValueError("platform cannot securely create evidence outputs")
    supported = getattr(os, "supports_dir_fd", set())
    for function in (os.open, os.mkdir, os.unlink, os.stat, os.rename):
        if function not in supported:
            raise ValueError("platform lacks descriptor-relative custody operations")


def _dir_flags() -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    return flags


def _canonical_artifact_relative(uri: str, *, label: str) -> Path:
    if not isinstance(uri, str):
        raise ValueError(f"{label} must be an artifact URI")
    match = ARTIFACT_URI.fullmatch(uri)
    if match is None:
        raise ValueError(f"{label} must use artifact:// with a scoped relative path")
    raw = match.group(1)
    relative = PurePosixPath(raw)
    if (
        relative.is_absolute()
        or any(part in {"", ".", ".."} for part in relative.parts)
        or relative.as_posix() != raw
    ):
        raise ValueError(f"{label} must use a canonical scoped relative path")
    return Path(*relative.parts)


def _resolved_custody_root(root: Path) -> Path:
    try:
        resolved = root.resolve(strict=True)
    except OSError as error:
        raise ValueError(f"custody root is unavailable: {error}") from error
    if not resolved.is_dir():
        raise ValueError("custody root must be a directory")
    return resolved


def _open_child(parent: int, component: str) -> int:
    try:
        return os.open(component, _dir_flags(), dir_fd=parent)
    except FileNotFoundError:
        try:
            os.mkdir(component, mode=0o700, dir_fd=parent)
        except FileExistsError:
            pass
        try:
            return os.open(component, _dir_flags(), dir_fd=parent)
        except OSError as error:
            raise ValueError(
                f"custody path contains an unsafe directory: {component}"
            ) from error
    except OSError as error:
        raise ValueError(
            f"custody path contains an unsafe directory: {component}"
        ) from error


def _create_relative_exclusive(
    resolved_root: Path,
    relative: Path,
    data: bytes,
    maximum: int,
) -> tuple[Path, str]:
    _require_output_api()
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError("custody output path is invalid")
    if len(data) > maximum:
        raise ValueError("custody output exceeds its byte bound")

    identities = _capture_absolute_directory_identity(
        resolved_root,
        label="custody root",
        fail=_fail,
    )
    opened: list[int] = []
    output: int | None = None
    created = False
    try:
        current = _open_absolute_directory_nofollow(
            resolved_root,
            label="custody root",
            fail=_fail,
            expected_identities=identities,
        )
        opened.append(current)
        for component in relative.parts[:-1]:
            current = _open_child(current, component)
            opened.append(current)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        try:
            output = os.open(relative.name, flags, 0o600, dir_fd=current)
            created = True
        except FileExistsError as error:
            raise ValueError(
                f"refusing to overwrite custody output: {resolved_root / relative}"
            ) from error
        except OSError as error:
            raise ValueError(
                f"cannot securely create custody output: {resolved_root / relative}"
            ) from error
        _write_all(output, data)
        os.fsync(output)
        state = os.fstat(output)
        if (
            not stat.S_ISREG(state.st_mode)
            or state.st_size != len(data)
            or state.st_mode & 0o077
        ):
            raise RuntimeError("custody output is incomplete or not private")
        os.fsync(current)
    except Exception:
        if created and opened:
            try:
                os.unlink(relative.name, dir_fd=opened[-1])
            except OSError:
                pass
        raise
    finally:
        if output is not None:
            os.close(output)
        for descriptor in reversed(opened):
            os.close(descriptor)
    return resolved_root / relative, hashlib.sha256(data).hexdigest()


def create_scoped_uri_exclusive(
    root: Path,
    uri: str,
    data: bytes,
    maximum: int,
    *,
    label: str,
) -> tuple[Path, str]:
    relative = _canonical_artifact_relative(uri, label=label)
    return _create_relative_exclusive(
        _resolved_custody_root(root),
        relative,
        data,
        maximum,
    )


def create_exclusive(
    root: Path,
    path: Path,
    data: bytes,
    maximum: int,
) -> tuple[Path, str]:
    resolved = _resolved_custody_root(root)
    try:
        relative = path.relative_to(resolved)
    except ValueError as error:
        raise ValueError("custody output escapes custody root") from error
    return _create_relative_exclusive(resolved, relative, data, maximum)


def write_signature(
    custody_root: Path,
    signature_uri: str,
    signature: bytes,
) -> tuple[Path, str]:
    return create_scoped_uri_exclusive(
        custody_root,
        signature_uri,
        signature,
        MAX_SIGNATURE_BYTES,
        label="detached signature",
    )


def bundle_bytes(bundle: dict[str, Any]) -> bytes:
    data = (
        json.dumps(bundle, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    if len(data) > MAX_JSON_BYTES:
        raise ValueError("output bundle exceeds the bounded JSON size")
    return data


def atomic_replace_bundle(snapshot: BundleSnapshot, data: bytes) -> tuple[Path, str]:
    _require_output_api()
    parent_fd = _open_absolute_directory_nofollow(
        snapshot.path.parent,
        label="external evidence bundle parent",
        fail=_fail,
        expected_identities=snapshot.directories,
    )
    current: int | None = None
    staged: int | None = None
    temporary: str | None = None
    renamed = False
    visible: int | None = None
    try:
        flags = os.O_RDONLY | os.O_NOFOLLOW
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        current = os.open(snapshot.path.name, flags, dir_fd=parent_fd)
        if _file_identity(os.fstat(current)) != snapshot.file_identity:
            raise ValueError("bundle file identity changed before update")
        current_bytes = _read_fd(current, "bundle", MAX_JSON_BYTES)
        if hashlib.sha256(current_bytes).hexdigest() != snapshot.sha256:
            raise ValueError("bundle bytes changed before update")

        for _ in range(16):
            temporary = f".{snapshot.path.name}.{secrets.token_hex(12)}.tmp"
            try:
                out_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                if hasattr(os, "O_CLOEXEC"):
                    out_flags |= os.O_CLOEXEC
                staged = os.open(temporary, out_flags, 0o600, dir_fd=parent_fd)
                break
            except FileExistsError:
                temporary = None
        if staged is None or temporary is None:
            raise RuntimeError("cannot allocate an exclusive bundle staging file")

        _write_all(staged, data)
        os.fsync(staged)
        staged_state = os.fstat(staged)
        if (
            not stat.S_ISREG(staged_state.st_mode)
            or staged_state.st_size != len(data)
            or staged_state.st_mode & 0o077
        ):
            raise RuntimeError("staged bundle is incomplete or not private")

        visible_state = os.stat(
            snapshot.path.name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
        if _file_identity(visible_state) != snapshot.file_identity:
            raise ValueError("bundle name changed before update")

        os.replace(
            temporary,
            snapshot.path.name,
            src_dir_fd=parent_fd,
            dst_dir_fd=parent_fd,
        )
        renamed = True
        os.fsync(parent_fd)

        visible = os.open(snapshot.path.name, flags, dir_fd=parent_fd)
        if _read_fd(visible, "updated bundle", MAX_JSON_BYTES) != data:
            raise RuntimeError("updated bundle bytes differ from staging")
        visible_state = os.fstat(visible)
        if visible_state.st_mode & 0o077:
            raise RuntimeError("updated bundle permissions are not private")

        verification_fd = _open_absolute_directory_nofollow(
            snapshot.path.parent,
            label="external evidence bundle parent",
            fail=_fail,
            expected_identities=snapshot.directories,
        )
        os.close(verification_fd)
    finally:
        if visible is not None:
            os.close(visible)
        if current is not None:
            os.close(current)
        if staged is not None:
            os.close(staged)
        if temporary is not None and not renamed:
            try:
                os.unlink(temporary, dir_fd=parent_fd)
            except OSError:
                pass
        os.close(parent_fd)
    return snapshot.path, hashlib.sha256(data).hexdigest()
