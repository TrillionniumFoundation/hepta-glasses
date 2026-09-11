from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from .core import (
    AUTHORITY,
    CLAIM,
    MAX_ARTIFACT_BYTES,
    MAX_SIGNATURE_BYTES,
    _read_bounded_file,
    canonical_submission_statement,
    fail,
    parse_time,
    require_bool,
    require_exact_keys,
    require_sha,
    require_string,
    require_string_array,
    safe_artifact_path,
    scan_secret_material,
    verify_ed25519_bytes,
    verify_ed25519_file,
)
from .trust import TrustKey, TrustRegistry


def _validate_signature_reference(
    *,
    artifact_root: Path,
    uri: Any,
    digest: Any,
    label: str,
) -> Path:
    path = safe_artifact_path(
        artifact_root,
        require_string(uri, label=f"{label}.uri", maximum=2000),
        label=f"{label}.uri",
    )
    data = _read_bounded_file(path, label=label, maximum=MAX_SIGNATURE_BYTES)
    expected = require_sha(digest, label=f"{label}.sha256", width=64)
    if hashlib.sha256(data).hexdigest() != expected:
        fail(f"{label} digest mismatch")
    return path


def validate_artifact(
    artifact: Any,
    *,
    artifact_root: Path,
    label: str,
    physical_only: bool,
    seen_artifacts: set[str],
    now: datetime,
    issuer_key: TrustKey,
    registry: TrustRegistry,
    issuer_identity: str,
    issuer_organization: str,
    issuer_authority_class: str,
    gap_id: str,
    openssl_binary: str,
) -> dict[str, Any]:
    if not isinstance(artifact, dict):
        fail(f"{label} must be an object")
    require_exact_keys(
        artifact,
        required={
            "artifact_id",
            "uri",
            "sha256",
            "media_type",
            "issued_at",
            "contains_secrets",
            "synthetic",
        },
        optional={"expires_at", "signature_uri", "signature_sha256"},
        label=label,
    )
    artifact_id = require_string(
        artifact["artifact_id"],
        label=f"{label}.artifact_id",
        maximum=200,
    )
    if artifact_id in seen_artifacts:
        fail(f"duplicate artifact_id: {artifact_id}")
    seen_artifacts.add(artifact_id)
    expected = require_sha(artifact["sha256"], label=f"{label}.sha256", width=64)
    require_string(artifact["media_type"], label=f"{label}.media_type", maximum=200)
    issued_at = parse_time(artifact["issued_at"], label=f"{label}.issued_at")
    assert issued_at is not None
    if issued_at > now:
        fail(f"{label}.issued_at is in the future")
    expires_at = parse_time(
        artifact.get("expires_at"),
        label=f"{label}.expires_at",
        nullable=True,
    )
    if expires_at is not None and expires_at <= now:
        fail(f"{label} is expired")
    if require_bool(artifact["contains_secrets"], label=f"{label}.contains_secrets"):
        fail(f"{label} declares prohibited secret content")
    synthetic = require_bool(artifact["synthetic"], label=f"{label}.synthetic")
    if physical_only and synthetic:
        fail(f"{label} is synthetic but the gap requires physical evidence")

    path = safe_artifact_path(
        artifact_root,
        require_string(artifact["uri"], label=f"{label}.uri", maximum=2000),
        label=label,
    )
    data = _read_bounded_file(path, label=label, maximum=MAX_ARTIFACT_BYTES)
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        fail(f"{label} digest mismatch: expected {expected}, got {actual}")
    scan_secret_material(path, label=label)

    signature_uri = artifact.get("signature_uri")
    signature_sha = artifact.get("signature_sha256")
    if (signature_uri is None) != (signature_sha is None):
        fail(f"{label} must provide both signature_uri and signature_sha256")
    native_signature_verified = False
    if signature_uri is not None:
        registry.require_key(
            key_id=issuer_key.key_id,
            identity=issuer_identity,
            organization=issuer_organization,
            authority_class=issuer_authority_class,
            gap_ids=[gap_id],
            usage="evidence_issuer",
            signed_at=issued_at,
            now=now,
            label=f"{label}.native_signature",
        )
        signature_path = _validate_signature_reference(
            artifact_root=artifact_root,
            uri=signature_uri,
            digest=signature_sha,
            label=f"{label}.native_signature",
        )
        verify_ed25519_file(
            public_key=issuer_key.public_key,
            message_path=path,
            signature_path=signature_path,
            openssl_binary=openssl_binary,
            label=f"{label}.native_signature",
        )
        native_signature_verified = True

    return {
        "artifact_id": artifact_id,
        "path": str(path),
        "sha256": actual,
        "synthetic": synthetic,
        "issued_at": issued_at.isoformat(),
        "expires_at": expires_at.isoformat() if expires_at else None,
        "native_signature_verified": native_signature_verified,
    }


def validate_candidate(
    candidate: Any,
    *,
    contract: Mapping[str, Any],
    expected_commit: str | None,
    expected_tree: str | None,
    now: datetime,
) -> dict[str, str]:
    if not isinstance(candidate, dict):
        fail("candidate must be an object")
    require_exact_keys(
        candidate,
        required={
            "repository",
            "source_commit",
            "source_tree",
            "contracts_revision",
            "collected_at",
        },
        optional={"release_id", "binary_digests"},
        label="candidate",
    )
    binding = contract["candidate_binding"]
    repository = require_string(candidate["repository"], label="candidate.repository", maximum=300)
    if repository != binding["repository"]:
        fail("candidate.repository differs from the evidence contract")
    commit = require_sha(candidate["source_commit"], label="candidate.source_commit", width=40)
    tree = require_sha(candidate["source_tree"], label="candidate.source_tree", width=40)
    if expected_commit is not None and commit != expected_commit:
        fail(f"candidate commit {commit} != expected {expected_commit}")
    if expected_tree is not None and tree != expected_tree:
        fail(f"candidate tree {tree} != expected {expected_tree}")
    revision = require_string(
        candidate["contracts_revision"],
        label="candidate.contracts_revision",
        maximum=100,
    )
    if revision != binding["contracts_revision"]:
        fail("candidate contracts revision differs from the evidence contract")
    collected = parse_time(candidate["collected_at"], label="candidate.collected_at")
    assert collected is not None
    if collected > now:
        fail("candidate.collected_at is in the future")

    release_id = candidate.get("release_id")
    if release_id is not None:
        require_string(release_id, label="candidate.release_id", maximum=200)
    binary_digests = candidate.get("binary_digests", [])
    if not isinstance(binary_digests, list) or len(binary_digests) > 32:
        fail("candidate.binary_digests must be a bounded array")
    seen_names: set[str] = set()
    for index, item in enumerate(binary_digests):
        if not isinstance(item, dict):
            fail(f"candidate.binary_digests[{index}] must be an object")
        require_exact_keys(
            item,
            required={"name", "sha256"},
            optional=set(),
            label=f"candidate.binary_digests[{index}]",
        )
        name = require_string(item["name"], label=f"candidate.binary_digests[{index}].name", maximum=200)
        if name in seen_names:
            fail(f"duplicate binary digest name: {name}")
        seen_names.add(name)
        require_sha(item["sha256"], label=f"candidate.binary_digests[{index}].sha256", width=64)

    return {
        "repository": repository,
        "commit": commit,
        "tree": tree,
        "revision": revision,
        "collected_at": collected.isoformat(),
    }


def validate_submission(
    submission: Any,
    *,
    bundle: Mapping[str, Any],
    index: int,
    contract: Mapping[str, Any],
    artifact_root: Path,
    seen_artifacts: set[str],
    registry: TrustRegistry,
    candidate_collected_at: datetime,
    now: datetime,
    openssl_binary: str,
) -> dict[str, Any]:
    label = f"submissions[{index}]"
    if not isinstance(submission, dict):
        fail(f"{label} must be an object")
    require_exact_keys(
        submission,
        required={
            "gap_id",
            "evidence_level",
            "issuer",
            "environment",
            "subjects",
            "claims",
            "artifacts",
            "result",
            "limitations",
            "attestation",
        },
        optional={"notes"},
        label=label,
    )
    gap_id = require_string(submission["gap_id"], label=f"{label}.gap_id", maximum=20)
    if gap_id not in set(contract["allowed_gap_ids"]):
        fail(f"{label}.gap_id is not authority-owned: {gap_id}")
    level = require_string(submission["evidence_level"], label=f"{label}.evidence_level", maximum=20)
    if level not in set(contract["allowed_levels"]):
        fail(f"{label}.evidence_level is not allowed: {level}")

    issuer = submission["issuer"]
    if not isinstance(issuer, dict):
        fail(f"{label}.issuer must be an object")
    require_exact_keys(
        issuer,
        required={"identity", "organization", "authority_class", "key_id"},
        optional={"contact"},
        label=f"{label}.issuer",
    )
    issuer_identity = require_string(
        issuer["identity"],
        label=f"{label}.issuer.identity",
        maximum=300,
    )
    issuer_organization = require_string(
        issuer["organization"],
        label=f"{label}.issuer.organization",
        maximum=300,
    )
    authority_class = require_string(
        issuer["authority_class"],
        label=f"{label}.issuer.authority_class",
        maximum=80,
    )
    if AUTHORITY.fullmatch(authority_class) is None:
        fail(f"{label}.issuer.authority_class is malformed")
    if authority_class not in set(contract["authority_classes"][gap_id]):
        fail(f"{label} issuer authority {authority_class} cannot attest {gap_id}")
    key_id = require_string(issuer["key_id"], label=f"{label}.issuer.key_id", maximum=500)
    if issuer.get("contact") is not None:
        require_string(issuer["contact"], label=f"{label}.issuer.contact", maximum=500)

    attestation = submission["attestation"]
    if not isinstance(attestation, dict):
        fail(f"{label}.attestation must be an object")
    require_exact_keys(
        attestation,
        required={"signed_at", "statement_digest", "signature_uri", "signature_sha256"},
        optional=set(),
        label=f"{label}.attestation",
    )
    signed_at = parse_time(attestation["signed_at"], label=f"{label}.attestation.signed_at")
    assert signed_at is not None
    if signed_at < candidate_collected_at:
        fail(f"{label}.attestation predates candidate collection")
    issuer_key = registry.require_key(
        key_id=key_id,
        identity=issuer_identity,
        organization=issuer_organization,
        authority_class=authority_class,
        gap_ids=[gap_id],
        usage="evidence_issuer",
        signed_at=signed_at,
        now=now,
        label=f"{label}.issuer",
    )

    environment = submission["environment"]
    if not isinstance(environment, dict) or not environment or len(environment) > 64:
        fail(f"{label}.environment must be a non-empty bounded object")
    for key, value in environment.items():
        if not isinstance(key, str) or CLAIM.fullmatch(key) is None:
            fail(f"{label}.environment has malformed key: {key!r}")
        if not isinstance(value, (str, int, float, bool)) and value is not None:
            fail(f"{label}.environment.{key} has a non-scalar value")
        if isinstance(value, float) and (value != value or value in {float("inf"), float("-inf")}):
            fail(f"{label}.environment.{key} contains a non-finite number")

    subjects = require_string_array(
        submission["subjects"],
        label=f"{label}.subjects",
        maximum=64,
        item_maximum=500,
    )
    claims = submission["claims"]
    if not isinstance(claims, dict) or not claims or len(claims) > 128:
        fail(f"{label}.claims must be a non-empty bounded object")
    for name, value in claims.items():
        if not isinstance(name, str) or CLAIM.fullmatch(name) is None:
            fail(f"{label}.claims contains malformed key: {name!r}")
        require_bool(value, label=f"{label}.claims.{name}")
    required_claims = set(contract["required_claims"][gap_id])
    missing_claims = required_claims - set(claims)
    if missing_claims:
        fail(f"{label} is missing required claims: {sorted(missing_claims)}")
    false_claims = sorted(name for name in required_claims if claims[name] is not True)
    if false_claims:
        fail(f"{label} has required claims that are not true: {false_claims}")

    artifacts = submission["artifacts"]
    if not isinstance(artifacts, list) or not (1 <= len(artifacts) <= 128):
        fail(f"{label}.artifacts must be a non-empty bounded array")
    artifact_results = [
        validate_artifact(
            artifact,
            artifact_root=artifact_root,
            label=f"{label}.artifacts[{artifact_index}]",
            physical_only=gap_id in set(contract["physical_evidence_only"]),
            seen_artifacts=seen_artifacts,
            now=now,
            issuer_key=issuer_key,
            registry=registry,
            issuer_identity=issuer_identity,
            issuer_organization=issuer_organization,
            issuer_authority_class=authority_class,
            gap_id=gap_id,
            openssl_binary=openssl_binary,
        )
        for artifact_index, artifact in enumerate(artifacts)
    ]
    if any(
        datetime.fromisoformat(item["issued_at"]) > signed_at
        for item in artifact_results
    ):
        fail(f"{label}.attestation predates one or more evidence artifacts")

    result = require_string(submission["result"], label=f"{label}.result", maximum=20)
    if result != "pass":
        fail(f"{label}.result must be pass before review eligibility")
    limitations = submission["limitations"]
    if not isinstance(limitations, list) or len(limitations) > 64:
        fail(f"{label}.limitations must be a bounded array")
    for limitation_index, limitation in enumerate(limitations):
        require_string(
            limitation,
            label=f"{label}.limitations[{limitation_index}]",
            maximum=1000,
        )
    if submission.get("notes") is not None:
        require_string(submission["notes"], label=f"{label}.notes", maximum=5000)

    statement = canonical_submission_statement(
        bundle,
        submission,
        contract_revision=contract["contract_revision"],
    )
    statement_digest = require_sha(
        attestation["statement_digest"],
        label=f"{label}.attestation.statement_digest",
        width=64,
    )
    actual_statement_digest = hashlib.sha256(statement).hexdigest()
    if statement_digest != actual_statement_digest:
        fail(f"{label}.attestation statement digest mismatch")
    signature_path = _validate_signature_reference(
        artifact_root=artifact_root,
        uri=attestation["signature_uri"],
        digest=attestation["signature_sha256"],
        label=f"{label}.attestation.signature",
    )
    verify_ed25519_bytes(
        public_key=issuer_key.public_key,
        message=statement,
        signature_path=signature_path,
        openssl_binary=openssl_binary,
        label=f"{label}.attestation",
    )

    return {
        "gap_id": gap_id,
        "evidence_level": level,
        "issuer_identity": issuer_identity,
        "issuer_organization": issuer_organization,
        "issuer_key_id": key_id,
        "authority_class": authority_class,
        "subjects": subjects,
        "artifacts": artifact_results,
        "required_claim_count": len(required_claims),
        "attestation_signed_at": signed_at.isoformat(),
        "attestation_statement_digest": actual_statement_digest,
    }

