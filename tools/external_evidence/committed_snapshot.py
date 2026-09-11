"""One byte/object snapshot across committed-evidence discovery and validation.

The verifier host/process is trusted. An untrusted repository writer may replace
any original evidence pathname; validation sees only a private read-only copy of
one bounded descriptor-checked capture. Both the original and copy are checked
again before a successful result can leave the context. This module never signs,
changes trust registries, supplies keys or manufactures evidence.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Iterator, Mapping

MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
MAX_ENTRIES = 100_000
MAX_DEPTH = 64
CONTRACT_ID = "hepta-external-evidence-envelope-v1"


class AdmissionSnapshotError(ValueError):
    """A custody failure; never an instruction to skip an evidence package."""


def _fail(message: str) -> None:
    raise AdmissionSnapshotError(message)


def _identity(value: os.stat_result) -> tuple[int, ...]:
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size,
            value.st_mtime_ns, value.st_ctime_ns)


def _object_identity(value: os.stat_result) -> tuple[int, ...]:
    return value.st_dev, value.st_ino, stat.S_IFMT(value.st_mode)


def _directory_flags() -> int:
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        _fail("no-follow directory API is required")
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)


def _open_root(path: Path) -> tuple[int, tuple[tuple[int, ...], ...]]:
    """Open every ancestor without following links; return one owned root fd."""
    descriptors: list[int] = []
    identities: list[tuple[int, ...]] = []
    try:
        current = os.open(path.anchor, _directory_flags())
        descriptors.append(current)
        identities.append(_object_identity(os.fstat(current)))
        for component in path.parts[1:]:
            current = os.open(component, _directory_flags(), dir_fd=current)
            descriptors.append(current)
            identities.append(_object_identity(os.fstat(current)))
        result = descriptors.pop()
        return result, tuple(identities)
    except OSError as error:
        raise AdmissionSnapshotError("evidence root has an unsafe or replaced ancestor") from error
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _regular_bytes(parent: int, name: str, initial: os.stat_result) -> bytes:
    if not stat.S_ISREG(initial.st_mode) or initial.st_size > MAX_FILE_BYTES:
        _fail("evidence entry is not a bounded regular file")
    # O_NONBLOCK also prevents a regular-file-to-FIFO race from hanging open().
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0) | os.O_NONBLOCK
    descriptor = os.open(name, flags, dir_fd=parent)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or _identity(before) != _identity(initial):
            _fail("evidence file changed before descriptor open")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, MAX_FILE_BYTES + 1 - total))
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_FILE_BYTES:
                _fail("evidence file exceeds byte bound")
            chunks.append(chunk)
        if _identity(os.fstat(descriptor)) != _identity(before) or total != before.st_size:
            _fail("evidence file changed during read")
        if _identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) != _identity(before):
            _fail("evidence file name changed after read")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _parse(payload: bytes) -> dict[str, Any] | None:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate JSON member")
            value[key] = item
        return value

    def constant(_: str) -> None:
        raise ValueError("non-finite JSON number")

    try:
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=unique,
                           parse_constant=constant)
    except (UnicodeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _content_digest(files: Mapping[str, bytes], directories: tuple[str, ...]) -> str:
    manifest = {
        "directories": list(directories),
        "files": [{"path": name, "sha256": hashlib.sha256(data).hexdigest()}
                  for name, data in sorted(files.items())],
    }
    return hashlib.sha256(json.dumps(manifest, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class CapturedRepository:
    root: Path
    files: Mapping[str, bytes]
    directories: tuple[str, ...]
    identities: Mapping[str, tuple[int, ...]]
    ancestors: tuple[tuple[int, ...], ...]
    digest: str

    def accepted(self) -> tuple[str, ...]:
        result = []
        for name, payload in sorted(self.files.items()):
            document = _parse(payload)
            if (document is not None and document.get("contract_id") == CONTRACT_ID
                    and isinstance(document.get("acceptance"), dict)
                    and document["acceptance"].get("state") == "accepted"):
                result.append(name)
        return tuple(result)

    def assert_current(self, *, phase: str) -> None:
        current = capture_repository(self.root)
        if (current.ancestors != self.ancestors or current.identities != self.identities
                or current.digest != self.digest):
            _fail(f"repository admission {phase} byte/object identity changed")


def capture_repository(base: Path) -> CapturedRepository:
    """Capture every regular file, not only envelopes; reject links and churn."""
    root = Path(os.path.abspath(os.fspath(base)))
    descriptor, ancestors = _open_root(root)
    files: dict[str, bytes] = {}
    directories: list[str] = []
    identities: dict[str, tuple[int, ...]] = {}
    total = entries = 0

    def walk(parent: int, relative: PurePosixPath, depth: int) -> None:
        nonlocal total, entries
        if depth > MAX_DEPTH:
            _fail("evidence snapshot exceeds depth bound")
        before = os.fstat(parent)
        name_here = relative.as_posix()
        directories.append(name_here)
        identities[name_here] = _identity(before)
        names: list[str] = []
        with os.scandir(parent) as iterator:
            for entry in iterator:
                entries += 1
                if entries > MAX_ENTRIES:
                    _fail("evidence snapshot exceeds entry bound")
                names.append(entry.name)
        names.sort()
        for name in names:
            if name in ("", ".", "..") or "/" in name or "\\" in name or "\x00" in name:
                _fail("non-canonical evidence entry name")
            initial = os.stat(name, dir_fd=parent, follow_symlinks=False)
            relative_name = (relative / name).as_posix()
            if stat.S_ISDIR(initial.st_mode):
                child = os.open(name, _directory_flags(), dir_fd=parent)
                try:
                    if _identity(os.fstat(child)) != _identity(initial):
                        _fail("evidence directory changed before open")
                    walk(child, relative / name, depth + 1)
                    if (_identity(os.fstat(child)) != _identity(initial)
                            or _identity(os.stat(name, dir_fd=parent, follow_symlinks=False))
                            != _identity(initial)):
                        _fail("evidence directory changed during capture")
                finally:
                    os.close(child)
            elif stat.S_ISREG(initial.st_mode):
                if initial.st_size > MAX_TOTAL_BYTES - total:
                    _fail("evidence snapshot exceeds aggregate byte bound")
                payload = _regular_bytes(parent, name, initial)
                total += len(payload)
                files[relative_name] = payload
                identities[relative_name] = _identity(initial)
            else:
                _fail("evidence snapshot rejects links and special objects")
        if _identity(os.fstat(parent)) != _identity(before):
            _fail("evidence directory changed during capture")

    try:
        walk(descriptor, PurePosixPath(), 0)
        visible, final_ancestors = _open_root(root)
        try:
            if (final_ancestors != ancestors
                    or _identity(os.fstat(visible)) != identities["."]):
                _fail("evidence root identity changed during capture")
        finally:
            os.close(visible)
    except OSError as error:
        raise AdmissionSnapshotError("evidence snapshot cannot read a stable tree") from error
    finally:
        os.close(descriptor)
    ordered = tuple(sorted(directories))
    return CapturedRepository(root, MappingProxyType(files), ordered,
                              MappingProxyType(identities), ancestors,
                              _content_digest(files, ordered))


@dataclass(frozen=True)
class ValidationSnapshot:
    captured: CapturedRepository
    root: Path

    def custody_root(self, name: str) -> Path:
        """Select custody using captured names, never the original filesystem."""
        current = PurePosixPath(name).parent
        while True:
            registry = (current / "trust-registry.json").as_posix()
            artifacts = (current / "artifacts").as_posix()
            if registry in self.captured.files:
                if artifacts not in self.captured.directories:
                    _fail("captured custody root lacks an artifact directory")
                return self.root.joinpath(*current.parts)
            if current == PurePosixPath():
                _fail("captured accepted envelope lacks a trust registry")
            current = current.parent


@contextmanager
def repository_validation_snapshot(base: Path) -> Iterator[ValidationSnapshot]:
    """Private immutable bytes bridge discovery and every validator file read."""
    captured = capture_repository(base)
    with tempfile.TemporaryDirectory(prefix="hepta-committed-snapshot-") as temporary:
        # Only the trusted, newly created temporary directory is resolved here;
        # untrusted repository pathnames are never resolved through symbolic links.
        root = Path(temporary).resolve() / "evidence"
        root.mkdir(mode=0o700)
        created_directories = [root]
        try:
            for name in sorted(captured.directories, key=lambda n: (len(PurePosixPath(n).parts), n)):
                if name == ".":
                    continue
                target = root.joinpath(*PurePosixPath(name).parts)
                target.mkdir(mode=0o700)
                created_directories.append(target)
            for name, payload in captured.files.items():
                target = root.joinpath(*PurePosixPath(name).parts)
                fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
                try:
                    remaining = memoryview(payload)
                    while remaining:
                        written = os.write(fd, remaining)
                        if written <= 0:
                            _fail("private evidence snapshot write stalled")
                        remaining = remaining[written:]
                finally:
                    os.close(fd)
            for target in reversed(created_directories):
                target.chmod(0o500)
            frozen = capture_repository(root)
            if frozen.digest != captured.digest:
                _fail("private evidence copy differs from captured bytes")
            captured.assert_current(phase="pre-validation")
            yield ValidationSnapshot(captured, root)
            # Nothing is returned to the authority caller until BOTH checks pass.
            frozen.assert_current(phase="private-post-validation")
            captured.assert_current(phase="post-validation")
        finally:
            for target in created_directories:
                # The trusted process owns this tree. Never chmod source paths.
                if target.is_dir() and not target.is_symlink():
                    target.chmod(0o700)


def validate_committed_packages(base: Path, *, expected_trust_registry_sha256: str | None) -> dict[str, Any]:
    """Canonical repository gate; no pluggable verifier, test clock or trust key.

    Existing accepted historical packages retain their signed candidate identity.
    This gate authenticates committed evidence, not the current source's release
    status. Product release must separately require the exact product candidate.
    """
    from tools import external_evidence

    with repository_validation_snapshot(base) as snapshot:
        packages = snapshot.captured.accepted()
        if packages and (not isinstance(expected_trust_registry_sha256, str)
                         or re.fullmatch(r"[0-9a-f]{64}", expected_trust_registry_sha256) is None):
            _fail("accepted committed packages require an out-of-band trust pin")
        results = []
        for name in packages:
            document = _parse(snapshot.captured.files[name])
            assert document is not None
            candidate = document.get("candidate")
            if not isinstance(candidate, dict):
                _fail("accepted envelope lacks candidate identity")
            commit, tree = candidate.get("source_commit"), candidate.get("source_tree")
            if any(not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{40}", value) is None
                   for value in (commit, tree)):
                _fail("accepted envelope candidate identity is malformed")
            custody = snapshot.custody_root(name)
            result = external_evidence.validate_bundle(
                snapshot.root.joinpath(*PurePosixPath(name).parts),
                artifact_root=custody / "artifacts",
                expected_commit=commit,
                expected_tree=tree,
                require_complete=True,
                require_accepted=True,
                trust_registry_path=custody / "trust-registry.json",
                expected_trust_registry_sha256=expected_trust_registry_sha256,
            )
            if (result.get("all_authority_owned_gaps_closed") is not True
                    or result.get("missing_gaps") != []
                    or result.get("missing_issuer_authority_classes") != {}
                    or result.get("review_set_integrity", {}).get("verified") is not True
                    or result.get("trust_registry", {}).get("external_pin_verified") is not True):
                _fail("committed evidence validator did not return complete acceptance")
            results.append({"path": name, "sha256": hashlib.sha256(snapshot.captured.files[name]).hexdigest(),
                            "candidate_commit": commit, "candidate_tree": tree})
        report = {"verified": True, "packages": results, "snapshot_sha256": snapshot.captured.digest,
                  "claim_ceiling": "committed package authentication only, not product release or independent review"}
    return report
