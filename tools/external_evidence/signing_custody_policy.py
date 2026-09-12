"""Transaction-wide lexical custody for authority-bearing signing commands."""

from __future__ import annotations

import contextvars
import functools
import os
import stat
from pathlib import Path
from types import ModuleType
from typing import Any

_OUTPUT_DIRECTORY: contextvars.ContextVar[Path | None] = contextvars.ContextVar(
    "hepta_external_evidence_output_directory",
    default=None,
)


def install_signing_io_policy(signing_io: ModuleType, core: ModuleType) -> None:
    """Make private-key reads and output creation share lexical lineage.

    The high-level signing command owns one validation snapshot. This installer
    ensures every custody-root and output-parent observation participates in
    that snapshot, rejects linked private-key and custody paths, and checks each
    child directory immediately after descriptor-relative open or creation.
    """

    base_capture_directory = signing_io._capture_absolute_directory_identity
    base_open_child = signing_io._open_child
    base_create_relative = signing_io._create_relative_exclusive

    def resolved_custody_root(root: Path) -> Path:
        if not isinstance(root, Path):
            raise ValueError("custody root must be a pathlib.Path")
        try:
            lexical, _ = core._validate_lexical_directory(
                root,
                label="custody root",
            )
        except core.EvidenceError as error:
            raise ValueError(str(error)) from error
        return lexical

    def capture_directory_identity(
        target: Path,
        *,
        label: str,
        fail: Any,
    ) -> tuple[tuple[int, int, int], ...]:
        identities = base_capture_directory(
            target,
            label=label,
            fail=fail,
        )
        core._pin_directory_identities(
            Path(os.path.abspath(os.fspath(target))),
            identities,
            label=label,
        )
        return identities

    def open_child(parent: int, component: str) -> int:
        parent_path = _OUTPUT_DIRECTORY.get()
        if parent_path is None:
            raise ValueError("custody child open occurred outside output transaction")
        descriptor = base_open_child(parent, component)
        child_path = parent_path / component
        try:
            identities = capture_directory_identity(
                child_path,
                label="custody output parent",
                fail=signing_io._fail,
            )
            state = os.fstat(descriptor)
            opened_identity = (
                state.st_dev,
                state.st_ino,
                stat.S_IFMT(state.st_mode),
            )
            if opened_identity != identities[-1]:
                raise ValueError(
                    "custody output parent changed between descriptor open "
                    "and lexical verification"
                )
        except Exception:
            os.close(descriptor)
            raise
        _OUTPUT_DIRECTORY.set(child_path)
        return descriptor

    def create_relative_exclusive(
        root: Path,
        relative: Path,
        data: bytes,
        maximum: int,
    ) -> tuple[Path, str]:
        lexical_root = resolved_custody_root(root)
        token = _OUTPUT_DIRECTORY.set(lexical_root)
        try:
            path, digest = base_create_relative(
                lexical_root,
                relative,
                data,
                maximum,
            )
            core._validate_lexical_directory(
                path.parent,
                label="custody output parent post-create",
            )
            return path, digest
        finally:
            _OUTPUT_DIRECTORY.reset(token)

    def read_private_key_snapshot(
        private_key: Path,
        *,
        forbidden_root: Path | None = None,
    ) -> bytes:
        lexical = Path(os.path.abspath(os.fspath(private_key)))
        if forbidden_root is not None:
            custody = resolved_custody_root(forbidden_root)
            try:
                lexical.relative_to(custody)
            except ValueError:
                pass
            else:
                raise ValueError("private key must remain outside evidence custody")
        try:
            data = core._stable_read_target(
                lexical,
                label="private key",
                maximum=core.MAX_PUBLIC_KEY_BYTES,
            )
        except core.EvidenceError as error:
            raise ValueError(str(error)) from error
        if b"PRIVATE KEY" not in data:
            raise ValueError(
                "private key file does not contain PEM private-key material"
            )
        return data

    signing_io._capture_absolute_directory_identity = capture_directory_identity
    signing_io._open_child = open_child
    signing_io._create_relative_exclusive = create_relative_exclusive
    signing_io._resolved_custody_root = resolved_custody_root
    signing_io.read_private_key_snapshot = read_private_key_snapshot


def install_signing_module_policy(signing: ModuleType, core: ModuleType) -> None:
    """Wrap every authority-bearing high-level signing transaction."""

    def resolved_custody_root(root: Any) -> Path:
        if not isinstance(root, Path):
            raise ValueError("--custody-root is required")
        try:
            lexical, _ = core._validate_lexical_directory(
                root,
                label="custody root",
            )
        except core.EvidenceError as error:
            raise ValueError(str(error)) from error
        return lexical

    signing._resolved_custody_root = resolved_custody_root

    for name in ("sign_submission", "sign_reviewer", "finalize"):
        original = getattr(signing, name)
        wrapped = core.validation_snapshot(original)
        functools.update_wrapper(wrapped, original)
        setattr(signing, name, wrapped)


__all__ = ["install_signing_io_policy", "install_signing_module_policy"]
