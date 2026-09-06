"""Signed inclusion, consistency and witness verification for Skill manifests.

The verifier consumes externally supplied facts under pinned public-key policy.
It does not operate a log, publish checkpoints, prove witness independence,
provide cross-client gossip or create a remote anti-rollback authority.
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
WITNESS_PREFIX = b"HEPTA-SKILL-TRANSPARENCY-WITNESS-V1\n"
MAX_CHECKPOINT_BYTES = 4096
MAX_WITNESS_STATEMENT_BYTES = 4096
MAX_AUDIT_PATH = 64
MAX_WITNESS_PROOFS = 64
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
_WITNESS_FIELDS = frozenset(
    {
        "schema_version",
        "witness_id",
        "key_id",
        "log_id",
        "tree_size",
        "root_sha256",
        "checkpoint_sha256",
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
class TransparencyCheckpointAnchor:
    """Pinned old tree root used only as a consistency-proof floor."""

    log_id: str
    tree_size: int
    root_sha256: str

    def __post_init__(self) -> None:
        name(self.log_id)
        if (
            type(self.tree_size) is not int
            or type(self.tree_size) is bool
            or not 1 <= self.tree_size <= (1 << 63) - 1
        ):
            fail("skill_transparency_anchor_invalid")
        digest(self.root_sha256)


@dataclass(frozen=True)
class TransparencyWitnessKey:
    """Externally governed witness identity/key binding."""

    witness_id: str
    public_der: bytes
    not_before: int
    not_after: int

    def __post_init__(self) -> None:
        name(self.witness_id)
        if (
            type(self.public_der) is not bytes
            or len(self.public_der) != 44
            or not self.public_der.startswith(SPKI_PREFIX)
            or not timestamp(self.not_before)
            or not timestamp(self.not_after)
            or self.not_before >= self.not_after
        ):
            fail("skill_transparency_witness_key_invalid")


@dataclass(frozen=True)
class TransparencyWitnessProof:
    statement: bytes
    signature: bytes


@dataclass(frozen=True)
class TransparencyProof:
    """Detached checkpoint, inclusion, consistency and witness material."""

    checkpoint: bytes
    signature: bytes
    leaf_index: int
    audit_path: tuple[bytes, ...]
    consistency_path: tuple[bytes, ...] = ()
    witnesses: tuple[TransparencyWitnessProof, ...] = ()


@dataclass(frozen=True)
class VerifiedTransparency:
    log_id: str
    key_id: str
    tree_size: int
    root_sha256: str
    leaf_index: int
    expires_at: int
    checkpoint_sha256: str
    consistency_verified: bool = False
    witness_ids: tuple[str, ...] = ()


def _canonical_record(raw: bytes, *, fields: frozenset[str], maximum: int,
                      size_code: str, format_code: str,
                      duplicate_code: str) -> dict[str, object]:
    if type(raw) is not bytes or not 1 <= len(raw) <= maximum:
        fail(size_code)

    def pairs(items):
        value = {}
        for key, child in items:
            if key in value:
                fail(duplicate_code)
            value[key] = child
        return value

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=lambda _: fail(format_code),
        )
        if type(value) is not dict or set(value) != fields or canonical(value) != raw:
            fail(format_code)
        return value
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        if getattr(error, "code", None):
            raise
        fail(format_code)
    raise AssertionError("unreachable")


def _checkpoint(raw: bytes) -> dict[str, object]:
    value = _canonical_record(
        raw,
        fields=_CHECKPOINT_FIELDS,
        maximum=MAX_CHECKPOINT_BYTES,
        size_code="skill_transparency_checkpoint_size_invalid",
        format_code="skill_transparency_checkpoint_format_invalid",
        duplicate_code="skill_transparency_checkpoint_duplicate_key",
    )
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


def _witness_statement(raw: bytes) -> dict[str, object]:
    value = _canonical_record(
        raw,
        fields=_WITNESS_FIELDS,
        maximum=MAX_WITNESS_STATEMENT_BYTES,
        size_code="skill_transparency_witness_statement_size_invalid",
        format_code="skill_transparency_witness_statement_format_invalid",
        duplicate_code="skill_transparency_witness_statement_duplicate_key",
    )
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        fail("skill_transparency_witness_statement_version_invalid")
    for field in ("witness_id", "key_id", "log_id"):
        name(value[field])
    if (
        type(value["tree_size"]) is not int
        or type(value["tree_size"]) is bool
        or not 1 <= value["tree_size"] <= (1 << 63) - 1
    ):
        fail("skill_transparency_witness_statement_invalid")
    digest(value["root_sha256"])
    digest(value["checkpoint_sha256"])
    if (
        not timestamp(value["issued_at"])
        or not timestamp(value["expires_at"])
        or not 0 < value["expires_at"] - value["issued_at"] <= 86400
    ):
        fail("skill_transparency_witness_statement_time_invalid")
    return value


def _leaf_hash(document: bytes) -> bytes:
    import hashlib
    return hashlib.sha256(b"\x00" + document).digest()


def _node_hash(left: bytes, right: bytes) -> bytes:
    import hashlib
    return hashlib.sha256(b"\x01" + left + right).digest()


def _proof_path(value: object, *, code: str) -> tuple[bytes, ...]:
    if (
        type(value) is not tuple
        or len(value) > MAX_AUDIT_PATH
        or any(type(item) is not bytes or len(item) != 32 for item in value)
    ):
        fail(code)
    return value


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
    ):
        fail("skill_transparency_inclusion_proof_invalid")
    audit_path = _proof_path(
        audit_path, code="skill_transparency_inclusion_proof_invalid"
    )
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


def _verify_consistency(
    old_size: int,
    new_size: int,
    old_root: bytes,
    new_root: bytes,
    proof: tuple[bytes, ...],
) -> None:
    """Verify an RFC6962 consistency proof without trusting a supplied old root."""
    proof = _proof_path(proof, code="skill_transparency_consistency_proof_invalid")
    if (
        type(old_size) is not int
        or type(old_size) is bool
        or type(new_size) is not int
        or type(new_size) is bool
        or not 1 <= old_size <= new_size <= (1 << 63) - 1
        or type(old_root) is not bytes
        or type(new_root) is not bytes
        or len(old_root) != 32
        or len(new_root) != 32
    ):
        fail("skill_transparency_consistency_proof_invalid")
    if old_size == new_size:
        if proof or old_root != new_root:
            fail("skill_transparency_consistency_proof_invalid")
        return

    fn = old_size - 1
    sn = new_size - 1
    while fn & 1:
        fn >>= 1
        sn >>= 1
    offset = 0
    if fn == 0:
        old_hash = old_root
        new_hash = old_root
    else:
        if not proof:
            fail("skill_transparency_consistency_proof_invalid")
        old_hash = proof[0]
        new_hash = proof[0]
        offset = 1
    for sibling in proof[offset:]:
        if sn == 0:
            fail("skill_transparency_consistency_proof_invalid")
        if fn & 1 or fn == sn:
            old_hash = _node_hash(sibling, old_hash)
            new_hash = _node_hash(sibling, new_hash)
            while fn != 0 and not (fn & 1):
                fn >>= 1
                sn >>= 1
        else:
            new_hash = _node_hash(new_hash, sibling)
        fn >>= 1
        sn >>= 1
    if sn != 0 or old_hash != old_root or new_hash != new_root:
        fail("skill_transparency_consistency_proof_invalid")


def _verify_detached(public_der: bytes, prefix: bytes, document: bytes,
                     signature: bytes, *, invalid_code: str) -> None:
    if type(signature) is not bytes or len(signature) != 64:
        fail(invalid_code)
    executable = trusted_openssl_path(
        fail=lambda _: fail("skill_transparency_verifier_runtime_unavailable")
    )
    try:
        with sealed_inputs((public_der, prefix + document, signature)) as descriptors:
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
        fail(invalid_code)


def _verify_signature(public_der: bytes, checkpoint: bytes, signature: bytes) -> None:
    _verify_detached(
        public_der,
        PREFIX,
        checkpoint,
        signature,
        invalid_code="skill_transparency_signature_invalid",
    )


class TransparencyVerifier:
    """Verify inclusion and optional anchored consistency/witness quorum."""

    __slots__ = (
        "_keys",
        "_clock",
        "_required",
        "_checkpoint_anchor",
        "_witness_keys",
        "_witness_quorum",
        "_binding",
        "_sealed",
    )

    def __setattr__(self, attribute: str, value: object) -> None:
        if getattr(self, "_sealed", False):
            fail("skill_transparency_configuration_immutable")
        object.__setattr__(self, attribute, value)

    def __init__(
        self,
        keys: Mapping[str, TransparencyLogKey],
        *,
        clock: Callable[[], int],
        required: bool = True,
        checkpoint_anchor: TransparencyCheckpointAnchor | None = None,
        witness_keys: Mapping[str, TransparencyWitnessKey] | None = None,
        witness_quorum: int = 0,
    ) -> None:
        if (
            not isinstance(keys, Mapping)
            or not 1 <= len(keys) <= 16
            or not callable(clock)
            or type(required) is not bool
            or (checkpoint_anchor is not None
                and type(checkpoint_anchor) is not TransparencyCheckpointAnchor)
            or (witness_keys is not None and not isinstance(witness_keys, Mapping))
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

        copied_witnesses: dict[str, TransparencyWitnessKey] = {}
        for key_id, key in (witness_keys or {}).items():
            name(key_id)
            if type(key) is not TransparencyWitnessKey:
                fail("skill_transparency_witness_key_invalid")
            copied_witnesses[key_id] = key
        if len(copied_witnesses) > 32 or len(
            {key.public_der for key in copied_witnesses.values()}
        ) != len(copied_witnesses):
            fail("skill_transparency_witness_key_alias")
        if type(witness_quorum) is not int or type(witness_quorum) is bool:
            fail("skill_transparency_witness_quorum_invalid")
        witness_id_count = len(
            {key.witness_id for key in copied_witnesses.values()}
        )
        if copied_witnesses:
            if not 1 <= witness_quorum <= witness_id_count:
                fail("skill_transparency_witness_quorum_invalid")
        elif witness_quorum != 0:
            fail("skill_transparency_witness_quorum_invalid")

        self._keys = MappingProxyType(copied)
        self._clock = clock
        self._required = required
        self._checkpoint_anchor = checkpoint_anchor
        self._witness_keys = MappingProxyType(copied_witnesses)
        self._witness_quorum = witness_quorum
        key_records = [
            {
                "key_id": key_id,
                "log_id": key.log_id,
                "public_key_sha256": sha256(key.public_der),
                "not_before": key.not_before,
                "not_after": key.not_after,
            }
            for key_id, key in sorted(copied.items())
        ]
        if checkpoint_anchor is None and not copied_witnesses:
            binding_value = {
                "schema_version": 1,
                "required": required,
                "keys": key_records,
            }
        else:
            binding_value = {
                "schema_version": 2,
                "required": required,
                "keys": key_records,
                "checkpoint_anchor": None
                if checkpoint_anchor is None
                else {
                    "log_id": checkpoint_anchor.log_id,
                    "tree_size": checkpoint_anchor.tree_size,
                    "root_sha256": checkpoint_anchor.root_sha256,
                },
                "witness_quorum": witness_quorum,
                "witness_keys": [
                    {
                        "key_id": key_id,
                        "witness_id": key.witness_id,
                        "public_key_sha256": sha256(key.public_der),
                        "not_before": key.not_before,
                        "not_after": key.not_after,
                    }
                    for key_id, key in sorted(copied_witnesses.items())
                ],
            }
        self._binding = sha256(canonical(binding_value))
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

    def _verify_witnesses(
        self,
        proof: TransparencyProof,
        verified: VerifiedTransparency,
        now: int,
    ) -> tuple[tuple[str, ...], int]:
        if not self._witness_keys:
            if proof.witnesses:
                fail("skill_transparency_witness_unconfigured")
            return (), verified.expires_at
        if (
            type(proof.witnesses) is not tuple
            or len(proof.witnesses) > MAX_WITNESS_PROOFS
        ):
            fail("skill_transparency_witness_proof_invalid")
        seen: set[str] = set()
        expiry = verified.expires_at
        for item in proof.witnesses:
            if type(item) is not TransparencyWitnessProof:
                fail("skill_transparency_witness_proof_invalid")
            statement = _witness_statement(item.statement)
            key = self._witness_keys.get(statement["key_id"])
            if key is None or key.witness_id != statement["witness_id"]:
                fail("skill_transparency_witness_key_mismatch")
            if key.witness_id in seen:
                fail("skill_transparency_witness_duplicate_identity")
            if (
                statement["log_id"] != verified.log_id
                or statement["tree_size"] != verified.tree_size
                or statement["root_sha256"] != verified.root_sha256
                or statement["checkpoint_sha256"] != verified.checkpoint_sha256
            ):
                fail("skill_transparency_witness_binding_mismatch")
            if (
                not key.not_before <= statement["issued_at"] <= now
                or now >= min(key.not_after, statement["expires_at"])
            ):
                fail("skill_transparency_witness_expired")
            if statement["expires_at"] > key.not_after:
                fail("skill_transparency_witness_outlives_key")
            _verify_detached(
                key.public_der,
                WITNESS_PREFIX,
                item.statement,
                item.signature,
                invalid_code="skill_transparency_witness_signature_invalid",
            )
            seen.add(key.witness_id)
            expiry = min(expiry, key.not_after, statement["expires_at"])
        if len(seen) < self._witness_quorum:
            fail("skill_transparency_witness_quorum_missing")
        return tuple(sorted(seen)), expiry

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
        checkpoint_digest = sha256(proof.checkpoint)
        verified = VerifiedTransparency(
            log_id=checkpoint["log_id"],
            key_id=checkpoint["key_id"],
            tree_size=checkpoint["tree_size"],
            root_sha256=checkpoint["root_sha256"],
            leaf_index=proof.leaf_index,
            expires_at=min(checkpoint["expires_at"], key.not_after),
            checkpoint_sha256=checkpoint_digest,
        )

        consistency_verified = False
        if self._checkpoint_anchor is None:
            if proof.consistency_path:
                fail("skill_transparency_consistency_unconfigured")
        else:
            if self._checkpoint_anchor.log_id != verified.log_id:
                fail("skill_transparency_consistency_log_mismatch")
            _verify_consistency(
                self._checkpoint_anchor.tree_size,
                verified.tree_size,
                bytes.fromhex(self._checkpoint_anchor.root_sha256),
                bytes.fromhex(verified.root_sha256),
                proof.consistency_path,
            )
            consistency_verified = True

        witness_ids, expiry = self._verify_witnesses(proof, verified, now)
        return VerifiedTransparency(
            log_id=verified.log_id,
            key_id=verified.key_id,
            tree_size=verified.tree_size,
            root_sha256=verified.root_sha256,
            leaf_index=verified.leaf_index,
            expires_at=expiry,
            checkpoint_sha256=verified.checkpoint_sha256,
            consistency_verified=consistency_verified,
            witness_ids=witness_ids,
        )
