from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .core import (
    AUTHORITY,
    CONTRACT_PATH,
    MAX_ARTIFACT_BYTES,
    _read_bounded_file,
    canonical_bundle_digest,
    canonical_review_statement,
    evidence_set_digest,
    fail,
    parse_time,
    read_object,
    require_exact_keys,
    require_sha,
    require_string,
    require_string_array,
    safe_artifact_path,
    scan_secret_material,
    verify_ed25519_bytes,
)
from .submission import _validate_signature_reference, validate_candidate, validate_submission
from .trust import TrustRegistry, load_trust_registry


def _validate_review_artifact(
    reviewer: Mapping[str, Any],
    *,
    artifact_root: Path,
    label: str,
) -> dict[str, str]:
    path = safe_artifact_path(
        artifact_root,
        require_string(reviewer["review_uri"], label=f"{label}.review_uri", maximum=2000),
        label=f"{label}.review_uri",
    )
    data = _read_bounded_file(path, label=f"{label}.review", maximum=MAX_ARTIFACT_BYTES)
    expected = require_sha(reviewer["review_sha256"], label=f"{label}.review_sha256", width=64)
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        fail(f"{label}.review digest mismatch")
    scan_secret_material(path, label=f"{label}.review")
    return {"path": str(path), "sha256": actual}


def validate_acceptance(
    acceptance: Any,
    *,
    bundle: Mapping[str, Any],
    submissions: list[dict[str, Any]],
    contract: Mapping[str, Any],
    artifact_root: Path,
    registry: TrustRegistry,
    require_accepted: bool,
    candidate_collected_at: datetime,
    now: datetime,
    openssl_binary: str,
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
        nullable=state in {"incomplete", "eligible_for_review"},
    )
    if reviewed_at is not None:
        if reviewed_at > now:
            fail("acceptance.reviewed_at is in the future")
        if reviewed_at < candidate_collected_at:
            fail("acceptance.reviewed_at predates candidate collection")

    reviewers = acceptance["reviewers"]
    if not isinstance(reviewers, list) or len(reviewers) > 32:
        fail("acceptance.reviewers must be a bounded array")
    if state in {"accepted", "rejected", "revoked"} and not reviewers:
        fail(f"acceptance state {state} requires at least one signed reviewer")

    submitted_gaps = {item["gap_id"] for item in submissions}
    issuer_key_ids = {item["issuer_key_id"] for item in submissions}
    issuer_identities = {item["issuer_identity"] for item in submissions}
    issuer_orgs_by_gap: dict[str, set[str]] = {}
    for item in submissions:
        issuer_orgs_by_gap.setdefault(item["gap_id"], set()).add(
            item["issuer_organization"]
        )
    latest_evidence_signature_time = max(
        datetime.fromisoformat(item["attestation_signed_at"])
        for item in submissions
    )

    reviewer_identities: set[str] = set()
    reviewer_key_ids: set[str] = set()
    independent_approvers: set[str] = set()
    approval_coverage: dict[str, list[str]] = {gap: [] for gap in submitted_gaps}
    independent_coverage: dict[str, list[str]] = {gap: [] for gap in submitted_gaps}
    review_results: list[dict[str, Any]] = []
    latest_signature_time: datetime | None = None

    for index, reviewer in enumerate(reviewers):
        label = f"acceptance.reviewers[{index}]"
        if not isinstance(reviewer, dict):
            fail(f"{label} must be an object")
        require_exact_keys(
            reviewer,
            required={
                "identity",
                "organization",
                "authority_class",
                "key_id",
                "decision",
                "reviewed_gap_ids",
                "review_uri",
                "review_sha256",
                "signed_at",
                "statement_digest",
                "signature_uri",
                "signature_sha256",
            },
            optional=set(),
            label=label,
        )
        identity = require_string(reviewer["identity"], label=f"{label}.identity", maximum=300)
        organization = require_string(
            reviewer["organization"],
            label=f"{label}.organization",
            maximum=300,
        )
        authority_class = require_string(
            reviewer["authority_class"],
            label=f"{label}.authority_class",
            maximum=80,
        )
        if AUTHORITY.fullmatch(authority_class) is None:
            fail(f"{label}.authority_class is malformed")
        key_id = require_string(reviewer["key_id"], label=f"{label}.key_id", maximum=500)
        if identity in reviewer_identities:
            fail(f"duplicate reviewer identity: {identity}")
        if key_id in reviewer_key_ids:
            fail(f"duplicate reviewer key_id: {key_id}")
        reviewer_identities.add(identity)
        reviewer_key_ids.add(key_id)
        if identity in issuer_identities or key_id in issuer_key_ids:
            fail(f"{label} is an evidence issuer alias and cannot review acceptance")

        decision = require_string(reviewer["decision"], label=f"{label}.decision", maximum=20)
        if decision not in {"approve", "reject", "abstain"}:
            fail(f"{label}.decision is invalid")
        reviewed_gaps = require_string_array(
            reviewer["reviewed_gap_ids"],
            label=f"{label}.reviewed_gap_ids",
            maximum=64,
            item_maximum=20,
        )
        if not set(reviewed_gaps).issubset(submitted_gaps):
            fail(f"{label}.reviewed_gap_ids contains a gap absent from the bundle")
        allowed_review_classes = contract["review_authority_classes"]
        for gap_id in reviewed_gaps:
            if authority_class not in set(allowed_review_classes[gap_id]):
                fail(f"{label} authority {authority_class} cannot review {gap_id}")

        signed_at = parse_time(reviewer["signed_at"], label=f"{label}.signed_at")
        assert signed_at is not None
        if signed_at < candidate_collected_at:
            fail(f"{label}.signed_at predates candidate collection")
        if signed_at < latest_evidence_signature_time:
            fail(f"{label}.signed_at predates submitted evidence attestations")
        key = registry.require_key(
            key_id=key_id,
            identity=identity,
            organization=organization,
            authority_class=authority_class,
            gap_ids=reviewed_gaps,
            usage="acceptance_reviewer",
            signed_at=signed_at,
            now=now,
            label=label,
        )
        is_independent = "independent_reviewer" in key.usages
        if is_independent and any(
            organization in issuer_orgs_by_gap.get(gap_id, set())
            for gap_id in reviewed_gaps
        ):
            fail(f"{label} is not organizationally independent from an evidence issuer")

        review_artifact = _validate_review_artifact(
            reviewer,
            artifact_root=artifact_root,
            label=label,
        )
        statement = canonical_review_statement(
            bundle,
            reviewer,
            contract_revision=contract["contract_revision"],
        )
        statement_digest = require_sha(
            reviewer["statement_digest"],
            label=f"{label}.statement_digest",
            width=64,
        )
        actual_statement_digest = hashlib.sha256(statement).hexdigest()
        if statement_digest != actual_statement_digest:
            fail(f"{label} statement digest mismatch")
        signature_path = _validate_signature_reference(
            artifact_root=artifact_root,
            uri=reviewer["signature_uri"],
            digest=reviewer["signature_sha256"],
            label=f"{label}.signature",
        )
        verify_ed25519_bytes(
            public_key=key.public_key,
            message=statement,
            signature_path=signature_path,
            openssl_binary=openssl_binary,
            label=label,
        )

        latest_signature_time = max(latest_signature_time or signed_at, signed_at)
        if decision == "approve":
            for gap_id in reviewed_gaps:
                approval_coverage[gap_id].append(identity)
                if is_independent:
                    independent_coverage[gap_id].append(identity)
            if is_independent:
                independent_approvers.add(identity)
        review_results.append(
            {
                "identity": identity,
                "organization": organization,
                "key_id": key_id,
                "authority_class": authority_class,
                "decision": decision,
                "reviewed_gap_ids": sorted(reviewed_gaps),
                "independent": is_independent,
                "review_artifact": review_artifact,
                "statement_digest": actual_statement_digest,
                "signed_at": signed_at.isoformat(),
            }
        )

    if reviewed_at is not None and latest_signature_time is not None:
        if reviewed_at < latest_signature_time:
            fail("acceptance.reviewed_at predates a signed reviewer decision")

    if state == "accepted":
        if any(item["decision"] == "reject" for item in review_results):
            fail("accepted bundle contains a rejecting review")
        missing_approval = sorted(
            gap_id for gap_id, reviewers_for_gap in approval_coverage.items() if not reviewers_for_gap
        )
        if missing_approval:
            fail(f"accepted bundle lacks approving reviewer coverage for gaps: {missing_approval}")
        independent_gaps = submitted_gaps & set(contract["independence_required"])
        missing_independent = sorted(
            gap_id for gap_id in independent_gaps if not independent_coverage[gap_id]
        )
        if missing_independent:
            fail(
                "accepted bundle lacks independent approving reviewer coverage for gaps: "
                f"{missing_independent}"
            )

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

    limitations = acceptance.get("limitations", [])
    if not isinstance(limitations, list) or len(limitations) > 64:
        fail("acceptance.limitations must be a bounded array")
    for index, value in enumerate(limitations):
        require_string(value, label=f"acceptance.limitations[{index}]", maximum=1000)
    if acceptance.get("decision_reference") is not None:
        require_string(
            acceptance["decision_reference"],
            label="acceptance.decision_reference",
            maximum=1000,
        )

    return {
        "state": state,
        "reviewed_at": reviewed_at.isoformat() if reviewed_at else None,
        "reviewers": review_results,
        "independent_approvers": sorted(independent_approvers),
        "approval_coverage": {key: sorted(value) for key, value in approval_coverage.items()},
        "independent_coverage": {
            key: sorted(value) for key, value in independent_coverage.items()
        },
        "evidence_set_digest": evidence_set_digest(bundle),
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
    trust_registry_path: Path | None = None,
    expected_trust_registry_sha256: str | None = None,
    openssl_binary: str = "openssl",
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    contract = read_object(CONTRACT_PATH, "external evidence contract")
    bundle = read_object(bundle_path, "external evidence bundle")
    require_exact_keys(
        bundle,
        required={
            "schema_version",
            "contract_id",
            "trust_registry",
            "candidate",
            "submissions",
            "acceptance",
        },
        optional=set(),
        label="bundle",
    )
    if bundle["schema_version"] != contract["schema_version"]:
        fail("bundle.schema_version differs from the canonical contract")
    if bundle["contract_id"] != contract["contract_id"]:
        fail("bundle.contract_id differs from the canonical contract")
    if not isinstance(bundle["trust_registry"], dict):
        fail("bundle.trust_registry must be an object")

    candidate = validate_candidate(
        bundle["candidate"],
        contract=contract,
        expected_commit=expected_commit,
        expected_tree=expected_tree,
        now=now,
    )
    candidate_collected_at = datetime.fromisoformat(candidate["collected_at"])
    registry = load_trust_registry(
        trust_registry_path,
        expected_digest=expected_trust_registry_sha256,
        bundle_binding=bundle["trust_registry"],
        contract=contract,
        now=now,
        openssl_binary=openssl_binary,
    )

    raw_submissions = bundle["submissions"]
    if not isinstance(raw_submissions, list) or not (1 <= len(raw_submissions) <= 64):
        fail("bundle.submissions must be a non-empty bounded array")
    seen_gaps: set[str] = set()
    seen_artifacts: set[str] = set()
    submissions: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_submissions):
        result = validate_submission(
            raw,
            bundle=bundle,
            index=index,
            contract=contract,
            artifact_root=artifact_root,
            seen_artifacts=seen_artifacts,
            registry=registry,
            candidate_collected_at=candidate_collected_at,
            now=now,
            openssl_binary=openssl_binary,
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
        artifact_root=artifact_root,
        registry=registry,
        require_accepted=require_accepted,
        candidate_collected_at=candidate_collected_at,
        now=now,
        openssl_binary=openssl_binary,
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
        "signature_profile": contract["signature_profile"],
        "trust_registry": {
            "registry_id": registry.registry_id,
            "sha256": registry.digest,
            "external_pin_verified": True,
            "expires_at": registry.expires_at.isoformat(),
        },
        "candidate": candidate,
        "submitted_gaps": sorted(seen_gaps),
        "missing_gaps": missing_gaps,
        "artifact_count": len(seen_artifacts),
        "submissions": submissions,
        "acceptance": acceptance,
        "eligible_for_review": eligible,
        "all_authority_owned_gaps_closed": closed,
    }
