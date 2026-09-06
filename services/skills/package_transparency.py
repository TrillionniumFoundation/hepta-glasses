"""Signed Merkle inclusion verification for exact Skill manifests.

This module verifies an externally pinned Ed25519 log checkpoint and an RFC6962
inclusion path. It does not operate a log, discover trust roots, provide gossip,
or prove that different clients observed the same tree.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Mapping

from services.control_plane.durable_state import timestamp
from services.skills.signed_package import (
    SPKI_PREFIX,
    canonical,
    digest,
    fail,
    name,
    sealed_inputs,
    sha256,
)
from tools.external_evidence.openssl_policy import (
    trusted_openssl_path,
    trusted_subprocess_environment,
)

PREFIX = b"HEPTA-SKILL-TRANSPARENCY-V1\n"
MAX_CHECKPOINT_BYTES = 4096
MAX_AUDIT_PATH = 64
_CHECKPOINT_FIELDS = frozenset(
    {
        "schema_version",
        "log_id",
        "key_id",
        "tree_size",
        "root_sha256",
        "issued_at",
        "expires_at",
    }
)


@dataclass(frozen=True)
class TransparencyLogKey:
    """One externally governed Ed25519 checkpoint-verification key."""

    log_id: str
    public_der: bytes
    not_before: int
    not_after: int

    def __post_init__(self) -> None:
        name(self.log_id)
        if (
            type(self.public_der) is not bytes
            or len(self.public_der) != 44
            or not self.public_der.startswith(SPKI_PREFIX)
            or not timestamp(self.not_before)
            or not timestamp(self.not_after)
            or self.not_before >= self.not_after
        ):
            fail("skill_transparency_public_key_invalid")


@dataclass(frozen=True)
class TransparencyProof:
    """Detached checkpoint signature and manifest inclusion path."""

    checkpoint: bytes
    signature: bytes
    leaf_index: int
    audit_path: tuple[bytes, ...]


@dataclass(frozen=True)
class VerifiedTransparency:
    log_id: str
    key_id: str
    tree_size: int
    root_sha256: str
    leaf_index: int
    expires_at: int
    checkpoint_sha256: str


def _checkpoint(raw: bytes) -> dict[str, object]:
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_CHECKPOINT_BYTES:
        fail("skill_transparency_checkpoint_size_invalid")

    def pairs(items):
        value = {}
        for key, child in items:
            if key in value:
                fail("skill_transparency_checkpoint_duplicate_key")
            value[key] = child
        return value

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=lambda _: fail("skill_transparency_checkpoint_format_invalid"),
        )
        if (
            type(value) is not dict
            or set(value) != _CHECKPOINT_FIELDS
            or canonical(value) != raw
        ):
            fail("skill_transparency_checkpoint_format_invalid")
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        # Preserve fixed domain errors but never expose parser internals.
        if getattr(error, "code", None):
            raise
        fail("skill_transparency_checkpoint_format_invalid")

    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        fail("skill_transparency_checkpoint_version_invalid")
    name(value["log_id"])
    name(value["key_id"])
    if (
        type(value["tree_size"]) is not int
        or type(value["tree_size"]) is bool
        or not 1 <= value["tree_size"] <= (1 << 63) - 1
    ):
        fail("skill_transparency_tree_size_invalid")
    digest(value["root_sha256"])
    if (
        not timestamp(value["issued_at"])
        or not timestamp(value["expires_at"])
        or not 0 < value["expires_at"] - value["issued_at"] <= 86400
    ):
        fail("skill_transparency_checkpoint_time_invalid")
    return value


def _leaf_hash(document: bytes) -> bytes:
    import hashlib

    return hashlib.sha256(b"\x00" + document).digest()


def _node_hash(left: bytes, right: bytes) -> bytes:
    import hashlib

    return hashlib.sha256(b"\x01" + left + right).digest()


def _verify_inclusion(
    document: bytes,
    *,
    leaf_index: int,
    tree_size: int,
    audit_path: tuple[bytes, ...],
    expected_root: bytes,
) -> None:
    if (
        type(leaf_index) is not int
        or type(leaf_index) is bool
        or not 0 <= leaf_index < tree_size
        or type(audit_path) is not tuple
        or len(audit_path) > MAX_AUDIT_PATH
        or any(type(item) is not bytes or len(item) != 32 for item in audit_path)
    ):
        fail("skill_transparency_inclusion_proof_invalid")

    node = _leaf_hash(document)
    fn = leaf_index
    sn = tree_size - 1
    for sibling in audit_path:
        if sn == 0:
            fail("skill_transparency_inclusion_proof_invalid")
        if fn & 1 or fn == sn:
            node = _node_hash(sibling, node)
            while fn != 0 and not (fn & 1):
                fn >>= 1
                sn >>= 1
        else:
            node = _node_hash(node, sibling)
        fn >>= 1
        sn >>= 1
    if sn != 0 or node != expected_root:
        fail("skill_transparency_inclusion_proof_invalid")


def _verify_signature(public_der: bytes, checkpoint: bytes, signature: bytes) -> None:
    if type(signature) is not bytes or len(signature) != 64:
        fail("skill_transparency_signature_invalid")
    executable = trusted_openssl_path(
        fail=lambda _: fail("skill_transparency_verifier_runtime_unavailable")
    )
    try:
        with sealed_inputs((public_der, PREFIX + checkpoint, signature)) as descriptors:
            public, message, detached = (
                f"/proc/self/fd/{descriptor}" for descriptor in descriptors
            )
            checked = subprocess.run(
                [
                    executable,
                    "pkeyutl",
                    "-verify",
                    "-pubin",
                    "-keyform",
                    "DER",
                    "-inkey",
                    public,
                    "-rawin",
                    "-in",
                    message,
                    "-sigfile",
                    detached,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                pass_fds=descriptors,
                timeout=5,
                check=False,
                env=trusted_subprocess_environment(),
            )
    except (OSError, subprocess.SubprocessError):
        fail("skill_transparency_verifier_runtime_unavailable")
    if checked.returncode != 0:
        fail("skill_transparency_signature_invalid")


class TransparencyVerifier:
    """Verify exact manifest inclusion under a fixed external log-key policy."""

    __slots__ = ("_keys", "_clock", "_required", "_binding", "_sealed")

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_sealed", False):
            fail("skill_transparency_configuration_immutable")
        object.__setattr__(self, name, value)

    def __init__(
        self,
        keys: Mapping[str, TransparencyLogKey],
        *,
        clock: Callable[[], int],
        required: bool = True,
    ) -> None:
        if (
            not isinstance(keys, Mapping)
            or not 1 <= len(keys) <= 16
            or not callable(clock)
            or type(required) is not bool
        ):
            fail("skill_transparency_configuration_invalid")
        copied: dict[str, TransparencyLogKey] = {}
        for key_id, key in keys.items():
            name(key_id)
            if type(key) is not TransparencyLogKey:
                fail("skill_transparency_public_key_invalid")
            copied[key_id] = key
        if len({key.public_der for key in copied.values()}) != len(copied):
            fail("skill_transparency_public_key_alias")
        self._keys = MappingProxyType(copied)
        self._clock = clock
        self._required = required
        self._binding = sha256(
            canonical(
                {
                    "schema_version": 1,
                    "required": required,
                    "keys": [
                        {
                            "key_id": key_id,
                            "log_id": key.log_id,
                            "public_key_sha256": sha256(key.public_der),
                            "not_before": key.not_before,
                            "not_after": key.not_after,
                        }
                        for key_id, key in sorted(copied.items())
                    ],
                }
            )
        )
        self._sealed = True

    @property
    def required(self) -> bool:
        return self._required

    @property
    def binding(self) -> str:
        return self._binding

    def _now(self) -> int:
        try:
            now = self._clock()
        except Exception:
            fail("skill_transparency_clock_invalid")
        if not timestamp(now):
            fail("skill_transparency_clock_invalid")
        return now

    def verify(
        self, document: bytes, proof: TransparencyProof | None
    ) -> VerifiedTransparency | None:
        if proof is None:
            if self.required:
                fail("skill_transparency_proof_required")
            return None
        if type(document) is not bytes or type(proof) is not TransparencyProof:
            fail("skill_transparency_proof_invalid")

        checkpoint = _checkpoint(proof.checkpoint)
        key = self._keys.get(checkpoint["key_id"])
        if key is None or key.log_id != checkpoint["log_id"]:
            fail("skill_transparency_log_key_mismatch")
        now = self._now()
        if (
            not key.not_before <= checkpoint["issued_at"] <= now
            or now >= min(key.not_after, checkpoint["expires_at"])
        ):
            fail("skill_transparency_checkpoint_expired")
        if checkpoint["expires_at"] > key.not_after:
            fail("skill_transparency_checkpoint_outlives_key")

        _verify_signature(key.public_der, proof.checkpoint, proof.signature)
        _verify_inclusion(
            document,
            leaf_index=proof.leaf_index,
            tree_size=checkpoint["tree_size"],
            audit_path=proof.audit_path,
            expected_root=bytes.fromhex(checkpoint["root_sha256"]),
        )
        return VerifiedTransparency(
            log_id=checkpoint["log_id"],
            key_id=checkpoint["key_id"],
            tree_size=checkpoint["tree_size"],
            root_sha256=checkpoint["root_sha256"],
            leaf_index=proof.leaf_index,
            expires_at=min(checkpoint["expires_at"], key.not_after),
            checkpoint_sha256=sha256(proof.checkpoint),
        )
