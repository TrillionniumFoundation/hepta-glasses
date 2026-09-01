#!/usr/bin/env python3
"""Validate authority-owned E5-E7/admin/upstream evidence without network access.

The validator deliberately distinguishes an evidence package that is structurally
eligible for independent review from an accepted closure package. It never edits
the Gap Ledger and it never treats synthetic evidence as physical evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "contracts/external-evidence-envelope-v1.json"
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA64 = re.compile(r"^[0-9a-f]{64}$")
AUTHORITY = re.compile(r"^[a-z][a-z0-9_]{2,79}$")
CLAIM = re.compile(r"^[a-z][a-z0-9_]{2,99}$")
ARTIFACT_URI = re.compile(r"^artifact://([A-Za-z0-9._/-]{1,500})$")
SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(rb"(?:OPENAI|DEEPSEEK|DASHSCOPE)_API_KEY\s*[:=]\s*[^\s]+", re.I),
    re.compile(rb"(?:refresh_token|client_secret)\s*[\"']?\s*[:=]\s*[\"'][^\"']{8,}", re.I),
)


class EvidenceError(AssertionError):
    """Stable fail-closed validation error."""


def fail(message: str) -> None:
    raise EvidenceError(message)


def read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:  # noqa: BLE001 - stable CLI boundary
        fail(f"{label} is not valid UTF-8 JSON: {error}")
    if not isinstance(value, dict):
        fail(f"{label} must contain a JSON object")
    return value


def require_exact_keys(
    value: dict[str, Any],
    *,
    required: set[str],
    optional: set[str],
    label: str,
) -> None:
    missing = required - value.keys()
    unknown = value.keys() - required - optional
    if missing:
        fail(f"{label} is missing keys: {sorted(missing)}")
    if unknown:
        fail(f"{label} has unknown keys: {sorted(unknown)}")


def require_string(value: Any, *, label: str, maximum: int = 5000) -> str:
    if not isinstance(value, str) or not value.strip():
        fail(f"{label} must be a non-empty string")
    normalized = value.strip()
    if len(normalized) > maximum:
        fail(f"{label} exceeds {maximum} characters")
    return normalized


def require_bool(value: Any, *, label: str) -> bool:
    if not isinstance(value, bool):
        fail(f"{label} must be boolean")
    return value


def parse_time(value: Any, *, label: str, nullable: bool = False) -> datetime | None:
    if value is None and nullable:
        return None
    text = require_string(value, label=label, maximum=100)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        fail(f"{label} is not an ISO-8601 timestamp: {error}")
    if parsed.tzinfo is None:
        fail(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def require_sha(value: Any, *, label: str, width: int) -> str:
    text = require_string(value, label=label, maximum=width)
    pattern = SHA40 if width == 40 else SHA64
    if pattern.fullmatch(text) is None:
        fail(f"{label} must be a lowercase {width}-hex digest")
    return text


def canonical_bundle_digest(bundle: dict[str, Any]) -> str:
    clone = json.loads(json.dumps(bundle))
    acceptance = clone.get("acceptance")
    if isinstance(acceptance, dict):
        acceptance["bundle_digest"] = None
    payload = json.dumps(
        clone,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def safe_artifact_path(root: Path, uri: str, *, label: str) -> Path:
    match = ARTIFACT_URI.fullmatch(uri)
    if match is None:
        fail(f"{label}.uri must use artifact:// with a repository-relative path")
    relative = PurePosixPath(match.group(1))
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        fail(f"{label}.uri escapes the artifact root")
    path = (root / Path(*relative.parts)).resolve()
    resolved_root = root.resolve()
    try:
        path.relative_to(resolved_root)
    except ValueError:
        fail(f"{label}.uri escapes the artifact root")
    return path


def scan_secret_material(path: Path, *, label: str) -> None:
    if path.stat().st_size > 256 * 1024 * 1024:
        fail(f"{label} exceeds the 256 MiB validation bound")
    data = path.read_bytes()
    for pattern in SECRET_PATTERNS:
        if pattern.search(data):
            fail(f"{label} contains prohibited credential-shaped material")


def validate_artifact(
    artifact: Any,
    *,
    artifact_root: Path,
    label: str,
    physical_only: bool,
    seen_artifacts: set[str],
    now: datetime,
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
    artifact_id = require_string(artifact["artifact_id"], label=f"{label}.artifact_id", maximum=200)
    if artifact_id in seen_artifacts:
        fail(f"duplicate artifact_id: {artifact_id}")
    seen_artifacts.add(artifact_id)
    expected = require_sha(artifact["sha256"], label=f"{label}.sha256", width=64)
    require_string(artifact["media_type"], label=f"{label}.media_type", maximum=200)
    issued_at = parse_time(artifact["issued_at"], label=f"{label}.issued_at")
    if issued_at is not None and issued_at > now:
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
    if not path.is_file():
        fail(f"{label} references a missing artifact: {path}")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        fail(f"{label} digest mismatch: expected {expected}, got {actual}")
    scan_secret_material(path, label=label)

    signature_uri = artifact.get("signature_uri")
    signature_sha = artifact.get("signature_sha256")
    if (signature_uri is None) != (signature_sha is None):
        fail(f"{label} must provide both signature_uri and signature_sha256")
    if signature_uri is not None:
        signature_path = safe_artifact_path(
            artifact_root,
            require_string(signature_uri, label=f"{label}.signature_uri", maximum=2000),
            label=f"{label}.signature",
        )
        if not signature_path.is_file():
            fail(f"{label} references a missing detached signature")
        expected_signature = require_sha(
            signature_sha,
            label=f"{label}.signature_sha256",
            width=64,
        )
        actual_signature = hashlib.sha256(signature_path.read_bytes()).hexdigest()
        if actual_signature != expected_signature:
            fail(f"{label} detached-signature digest mismatch")
        scan_secret_material(signature_path, label=f"{label}.signature")

    return {
        "artifact_id": artifact_id,
        "path": str(path),
        "sha256": actual,
        "synthetic": synthetic,
        "expires_at": expires_at.isoformat() if expires_at else None,
    }


def validate_candidate(
    candidate: Any,
    *,
    contract: dict[str, Any],
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
    if collected is not None and collected > now:
        fail("candidate.collected_at is in the future")

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

    return {"repository": repository, "commit": commit, "tree": tree, "revision": revision}


def validate_submission(
    submission: Any,
    *,
    index: int,
    contract: dict[str, Any],
    artifact_root: Path,
    seen_artifacts: set[str],
    now: datetime,
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
        },
        optional={"notes"},
        label=label,
    )
    gap_id = require_string(submission["gap_id"], label=f"{label}.gap_id", maximum=20)
    allowed_gaps = set(contract["allowed_gap_ids"])
    if gap_id not in allowed_gaps:
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
    issuer_identity = require_string(issuer["identity"], label=f"{label}.issuer.identity", maximum=300)
    require_string(issuer["organization"], label=f"{label}.issuer.organization", maximum=300)
    authority_class = require_string(
        issuer["authority_class"],
        label=f"{label}.issuer.authority_class",
        maximum=80,
    )
    if AUTHORITY.fullmatch(authority_class) is None:
        fail(f"{label}.issuer.authority_class is malformed")
    if authority_class not in set(contract["authority_classes"][gap_id]):
        fail(f"{label} issuer authority {authority_class} cannot attest {gap_id}")
    require_string(issuer["key_id"], label=f"{label}.issuer.key_id", maximum=500)

    environment = submission["environment"]
    if not isinstance(environment, dict) or not environment or len(environment) > 64:
        fail(f"{label}.environment must be a non-empty bounded object")
    for key, value in environment.items():
        if not isinstance(key, str) or CLAIM.fullmatch(key) is None:
            fail(f"{label}.environment has malformed key: {key!r}")
        if not isinstance(value, (str, int, float, bool)) and value is not None:
            fail(f"{label}.environment.{key} has a non-scalar value")

    subjects = submission["subjects"]
    if not isinstance(subjects, list) or not subjects or len(subjects) > 64:
        fail(f"{label}.subjects must be a non-empty bounded array")
    normalized_subjects = [
        require_string(value, label=f"{label}.subjects[{i}]", maximum=500)
        for i, value in enumerate(subjects)
    ]
    if len(set(normalized_subjects)) != len(normalized_subjects):
        fail(f"{label}.subjects contains duplicates")

    claims = submission["claims"]
    if not isinstance(claims, dict) or not claims or len(claims) > 128:
        fail(f"{label}.claims must be a non-empty bounded object")
    for name, value in claims.items():
        if not isinstance(name, str) or CLAIM.fullmatch(name) is None:
            fail(f"{label}.claims contains malformed key: {name!r}")
        require_bool(value, label=f"{label}.claims.{name}")
    required_claims = set(contract["required_claims"][gap_id])
    missing_claims = required_claims - claims.keys()
    if missing_claims:
        fail(f"{label} is missing required claims: {sorted(missing_claims)}")
    false_claims = sorted(name for name in required_claims if claims[name] is not True)
    if false_claims:
        fail(f"{label} has required claims that are not true: {false_claims}")

    artifacts = submission["artifacts"]
    if not isinstance(artifacts, list) or not artifacts or len(artifacts) > 128:
        fail(f"{label}.artifacts must be a non-empty bounded array")
    artifact_results = [
        validate_artifact(
            artifact,
            artifact_root=artifact_root,
            label=f"{label}.artifacts[{artifact_index}]",
            physical_only=gap_id in set(contract["physical_evidence_only"]),
            seen_artifacts=seen_artifacts,
            now=now,
        )
        for artifact_index, artifact in enumerate(artifacts)
    ]

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

    return {
        "gap_id": gap_id,
        "evidence_level": level,
        "issuer_identity": issuer_identity,
        "authority_class": authority_class,
        "artifacts": artifact_results,
        "required_claim_count": len(required_claims),
    }


def validate_acceptance(
    acceptance: Any,
    *,
    bundle: dict[str, Any],
    submissions: list[dict[str, Any]],
    contract: dict[str, Any],
    require_accepted: bool,
    now: datetime,
) -> dict[str, Any]:
    if not isinstance(acceptance, dict):
        fail("acceptance must be an object")
    require_exact_keys(
        acceptance,
        required={"state", "reviewed_at", "reviewers", "bundle_digest"},
        optional={"decision_reference", "limitations"},
        label="acceptance",
    )
    state = require_string(acceptance["state"], label="acceptance.state", maximum=40)
    if state not in set(contract["closure_states"]):
        fail(f"acceptance.state is unknown: {state}")
    if require_accepted and state != "accepted":
        fail("bundle is not accepted")
    reviewed_at = parse_time(
        acceptance["reviewed_at"],
        label="acceptance.reviewed_at",
        nullable=state == "incomplete",
    )
    if reviewed_at is not None and reviewed_at > now:
        fail("acceptance.reviewed_at is in the future")

    reviewers = acceptance["reviewers"]
    if not isinstance(reviewers, list) or len(reviewers) > 16:
        fail("acceptance.reviewers must be a bounded array")
    if state in {"eligible_for_review", "accepted", "rejected", "revoked"} and not reviewers:
        fail(f"acceptance state {state} requires at least one reviewer")
    issuer_identities = {item["issuer_identity"] for item in submissions}
    reviewer_identities: set[str] = set()
    independent_approvers: set[str] = set()
    for index, reviewer in enumerate(reviewers):
        label = f"acceptance.reviewers[{index}]"
        if not isinstance(reviewer, dict):
            fail(f"{label} must be an object")
        require_exact_keys(
            reviewer,
            required={
                "identity",
                "organization",
                "independent",
                "decision",
                "review_digest",
            },
            optional={"signature_uri"},
            label=label,
        )
        identity = require_string(reviewer["identity"], label=f"{label}.identity", maximum=300)
        if identity in reviewer_identities:
            fail(f"duplicate reviewer identity: {identity}")
        reviewer_identities.add(identity)
        require_string(reviewer["organization"], label=f"{label}.organization", maximum=300)
        independent = require_bool(reviewer["independent"], label=f"{label}.independent")
        decision = require_string(reviewer["decision"], label=f"{label}.decision", maximum=20)
        if decision not in {"approve", "reject", "abstain"}:
            fail(f"{label}.decision is invalid")
        require_sha(reviewer["review_digest"], label=f"{label}.review_digest", width=64)
        if identity in issuer_identities and independent:
            fail(f"{label} claims independence but also issued evidence")
        if independent and decision == "approve":
            independent_approvers.add(identity)

    submitted_gaps = {item["gap_id"] for item in submissions}
    independent_gaps = submitted_gaps & set(contract["independence_required"])
    if state == "accepted" and independent_gaps and not independent_approvers:
        fail(
            "accepted bundle includes independent-review gaps but has no "
            "independent approving reviewer"
        )
    if state == "accepted" and any(
        reviewer.get("decision") == "reject" for reviewer in reviewers
    ):
        fail("accepted bundle contains a rejecting review")

    computed_digest = canonical_bundle_digest(bundle)
    supplied = acceptance["bundle_digest"]
    if state == "incomplete" and supplied is None:
        pass
    else:
        supplied_digest = require_sha(supplied, label="acceptance.bundle_digest", width=64)
        if supplied_digest != computed_digest:
            fail(
                "acceptance.bundle_digest mismatch: "
                f"expected {computed_digest}, got {supplied_digest}"
            )

    return {
        "state": state,
        "reviewed_at": reviewed_at.isoformat() if reviewed_at else None,
        "reviewers": sorted(reviewer_identities),
        "independent_approvers": sorted(independent_approvers),
        "computed_bundle_digest": computed_digest,
    }


def validate_bundle(
    bundle_path: Path,
    *,
    artifact_root: Path,
    expected_commit: str | None,
    expected_tree: str | None,
    require_complete: bool,
    require_accepted: bool,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    contract = read_object(CONTRACT_PATH, "external evidence contract")
    bundle = read_object(bundle_path, "external evidence bundle")
    require_exact_keys(
        bundle,
        required={"schema_version", "contract_id", "candidate", "submissions", "acceptance"},
        optional=set(),
        label="bundle",
    )
    if bundle["schema_version"] != 1:
        fail("bundle.schema_version must be 1")
    if bundle["contract_id"] != contract["contract_id"]:
        fail("bundle.contract_id differs from the canonical contract")
    candidate = validate_candidate(
        bundle["candidate"],
        contract=contract,
        expected_commit=expected_commit,
        expected_tree=expected_tree,
        now=now,
    )

    raw_submissions = bundle["submissions"]
    if not isinstance(raw_submissions, list) or not raw_submissions or len(raw_submissions) > 64:
        fail("bundle.submissions must be a non-empty bounded array")
    seen_gaps: set[str] = set()
    seen_artifacts: set[str] = set()
    submissions: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_submissions):
        result = validate_submission(
            raw,
            index=index,
            contract=contract,
            artifact_root=artifact_root,
            seen_artifacts=seen_artifacts,
            now=now,
        )
        if result["gap_id"] in seen_gaps:
            fail(f"duplicate gap submission: {result['gap_id']}")
        seen_gaps.add(result["gap_id"])
        submissions.append(result)

    required_gaps = set(contract["allowed_gap_ids"])
    missing_gaps = sorted(required_gaps - seen_gaps)
    if require_complete and missing_gaps:
        fail(f"complete bundle is missing authority-owned gaps: {missing_gaps}")

    acceptance = validate_acceptance(
        bundle["acceptance"],
        bundle=bundle,
        submissions=submissions,
        contract=contract,
        require_accepted=require_accepted,
        now=now,
    )
    eligible = not missing_gaps and acceptance["state"] in {
        "eligible_for_review",
        "accepted",
    }
    closed = eligible and acceptance["state"] == "accepted"
    return {
        "ok": True,
        "contract_id": contract["contract_id"],
        "contract_revision": contract["contract_revision"],
        "candidate": candidate,
        "submitted_gaps": sorted(seen_gaps),
        "missing_gaps": missing_gaps,
        "artifact_count": len(seen_artifacts),
        "acceptance": acceptance,
        "eligible_for_review": eligible,
        "all_authority_owned_gaps_closed": closed,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--artifact-root", required=True, type=Path)
    parser.add_argument("--expected-commit")
    parser.add_argument("--expected-tree")
    parser.add_argument("--require-complete", action="store_true")
    parser.add_argument("--require-accepted", action="store_true")
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        expected_commit = (
            require_sha(args.expected_commit, label="--expected-commit", width=40)
            if args.expected_commit
            else None
        )
        expected_tree = (
            require_sha(args.expected_tree, label="--expected-tree", width=40)
            if args.expected_tree
            else None
        )
        result = validate_bundle(
            args.bundle,
            artifact_root=args.artifact_root,
            expected_commit=expected_commit,
            expected_tree=expected_tree,
            require_complete=args.require_complete,
            require_accepted=args.require_accepted,
        )
    except EvidenceError as error:
        result = {"ok": False, "error": str(error)}
        payload = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(payload, encoding="utf-8")
        sys.stderr.write(payload)
        return 1

    payload = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    sys.stdout.write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
