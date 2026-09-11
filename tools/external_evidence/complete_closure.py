"""Versioned complete external-evidence closure policy.

G10 layers three fail-closed rules over the authenticated G9 primitives:

* every authority class named for a gap participates through a distinct key and
  identity/organization seat;
* each issuer signs exactly the claims assigned to its authority class by the
  versioned canonical contract; and
* every final reviewer co-signs the same ordered reviewer roster and acceptance
  context through a manifest embedded in the already signed review artifact.

The underlying artifact, key, candidate, Ed25519, time, independence, and
filesystem-custody checks remain in the G9 modules.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .acceptance import validate_acceptance
from .core import (
    CONTRACT_PATH,
    MAX_ARTIFACT_BYTES,
    canonical_digest,
    fail,
    read_object,
    require_exact_keys,
    require_sha,
    require_string,
    safe_artifact_path,
)
from .submission import validate_candidate, validate_submission
from .trust import load_trust_registry

_POLICY_ID = "hepta-external-complete-closure-v1"
_POLICY_REVISION = "2026-09-02-g10-quorum-1"
_REVIEW_MANIFEST_VERSION = 1
_REVIEW_SET_STATEMENT = "hepta.external-evidence-review-set.v1"
_ACCEPTANCE_CONTEXT_STATEMENT = "hepta.external-evidence-acceptance-context.v1"


def _validate_contract_policy(
    contract: Mapping[str, Any],
) -> dict[str, dict[str, list[str]]]:
    if contract.get("contract_revision") != _POLICY_REVISION:
        fail(
            "external evidence contract revision does not select the G10 "
            "complete-closure policy"
        )
    if contract.get("extends_contract_revision") != (
        "2026-09-02-g9-authenticated-1"
    ):
        fail("G10 contract does not identify its authenticated G9 predecessor")

    profile = contract.get("complete_closure_profile")
    if not isinstance(profile, dict):
        fail("external evidence contract lacks complete_closure_profile")
    require_exact_keys(
        profile,
        required={
            "policy_id",
            "policy_revision",
            "issuer_authority_mode",
            "issuer_claim_mode",
            "distinct_key_per_gap",
            "distinct_identity_organization_pair_per_gap",
            "review_manifest_schema_version",
            "review_set_statement_type",
            "acceptance_context_statement_type",
            "review_manifest_required_for_states",
        },
        optional=set(),
        label="complete_closure_profile",
    )
    expected_scalars = {
        "policy_id": _POLICY_ID,
        "policy_revision": _POLICY_REVISION,
        "issuer_authority_mode": "all_named_classes",
        "issuer_claim_mode": "exact_class_scoped_claims",
        "distinct_key_per_gap": True,
        "distinct_identity_organization_pair_per_gap": True,
        "review_manifest_schema_version": _REVIEW_MANIFEST_VERSION,
        "review_set_statement_type": _REVIEW_SET_STATEMENT,
        "acceptance_context_statement_type": _ACCEPTANCE_CONTEXT_STATEMENT,
        "review_manifest_required_for_states": ["accepted"],
    }
    for key, expected in expected_scalars.items():
        if profile.get(key) != expected:
            fail(f"complete_closure_profile.{key} drifted")

    allowed_gaps = contract.get("allowed_gap_ids")
    authority_classes = contract.get("authority_classes")
    all_claims = contract.get("required_claims")
    raw_scopes = contract.get("required_claims_by_authority_class")
    if not isinstance(allowed_gaps, list):
        fail("evidence contract allowed_gap_ids must be an array")
    if not isinstance(authority_classes, dict):
        fail("evidence contract authority_classes must be an object")
    if not isinstance(all_claims, dict):
        fail("evidence contract required_claims must be an object")
    if not isinstance(raw_scopes, dict):
        fail(
            "evidence contract required_claims_by_authority_class must be an "
            "object"
        )

    gap_set = set(allowed_gaps)
    if set(authority_classes) != gap_set:
        fail("authority_classes gap set differs from allowed_gap_ids")
    if set(all_claims) != gap_set:
        fail("required_claims gap set differs from allowed_gap_ids")
    if set(raw_scopes) != gap_set:
        fail(
            "required_claims_by_authority_class gap set differs from "
            "allowed_gap_ids"
        )

    normalized: dict[str, dict[str, list[str]]] = {}
    for gap_id in allowed_gaps:
        classes = authority_classes[gap_id]
        claims = all_claims[gap_id]
        scopes = raw_scopes[gap_id]
        if not isinstance(classes, list) or not classes:
            fail(f"authority_classes.{gap_id} must be non-empty")
        if not isinstance(claims, list) or not claims:
            fail(f"required_claims.{gap_id} must be non-empty")
        if not isinstance(scopes, dict):
            fail(
                f"required_claims_by_authority_class.{gap_id} must be an "
                "object"
            )
        class_names = {
            require_string(
                value,
                label=f"authority_classes.{gap_id}",
                maximum=80,
            )
            for value in classes
        }
        if len(class_names) != len(classes):
            fail(f"authority_classes.{gap_id} contains duplicates")
        if set(scopes) != class_names:
            fail(
                f"claim-scope authority classes for {gap_id} differ from the "
                "required authority seats"
            )

        required_claims = {
            require_string(
                value,
                label=f"required_claims.{gap_id}",
                maximum=100,
            )
            for value in claims
        }
        if len(required_claims) != len(claims):
            fail(f"required_claims.{gap_id} contains duplicates")

        assigned: set[str] = set()
        normalized[gap_id] = {}
        for authority_class in classes:
            scoped = scopes[authority_class]
            if not isinstance(scoped, list) or not scoped:
                fail(
                    f"required_claims_by_authority_class.{gap_id}."
                    f"{authority_class} must be non-empty"
                )
            scoped_claims = [
                require_string(
                    value,
                    label=(
                        "required_claims_by_authority_class."
                        f"{gap_id}.{authority_class}"
                    ),
                    maximum=100,
                )
                for value in scoped
            ]
            scoped_set = set(scoped_claims)
            if len(scoped_set) != len(scoped_claims):
                fail(
                    f"claim scope {gap_id}/{authority_class} contains "
                    "duplicates"
                )
            overlap = assigned & scoped_set
            if overlap:
                fail(
                    f"claims {sorted(overlap)} are assigned to multiple "
                    f"authority classes for {gap_id}"
                )
            assigned.update(scoped_set)
            normalized[gap_id][authority_class] = scoped_claims
        if assigned != required_claims:
            missing = sorted(required_claims - assigned)
            unknown = sorted(assigned - required_claims)
            fail(
                f"class-scoped claims for {gap_id} do not partition required "
                f"claims; missing={missing}, unknown={unknown}"
            )

    return normalized


def _review_projection(
    reviewer: Mapping[str, Any],
    *,
    label: str,
) -> dict[str, Any]:
    reviewed_gap_ids = reviewer.get("reviewed_gap_ids")
    if not isinstance(reviewed_gap_ids, list) or not reviewed_gap_ids:
        fail(f"{label}.reviewed_gap_ids must be a non-empty array")
    normalized_gaps = [
        require_string(
            value,
            label=f"{label}.reviewed_gap_ids[{index}]",
            maximum=20,
        )
        for index, value in enumerate(reviewed_gap_ids)
    ]
    if len(set(normalized_gaps)) != len(normalized_gaps):
        fail(f"{label}.reviewed_gap_ids contains duplicates")
    return {
        "identity": require_string(
            reviewer.get("identity"),
            label=f"{label}.identity",
            maximum=300,
        ),
        "organization": require_string(
            reviewer.get("organization"),
            label=f"{label}.organization",
            maximum=300,
        ),
        "authority_class": require_string(
            reviewer.get("authority_class"),
            label=f"{label}.authority_class",
            maximum=80,
        ),
        "key_id": require_string(
            reviewer.get("key_id"),
            label=f"{label}.key_id",
            maximum=500,
        ),
        "decision": require_string(
            reviewer.get("decision"),
            label=f"{label}.decision",
            maximum=20,
        ),
        "reviewed_gap_ids": sorted(normalized_gaps),
        "signed_at": require_string(
            reviewer.get("signed_at"),
            label=f"{label}.signed_at",
            maximum=100,
        ),
    }


def review_set_digest(reviewers: Sequence[Mapping[str, Any]]) -> str:
    """Digest one ordered final reviewer roster under the G10 policy."""

    projections = [
        _review_projection(reviewer, label=f"reviewers[{index}]")
        for index, reviewer in enumerate(reviewers)
    ]
    return canonical_digest(
        {
            "statement_type": _REVIEW_SET_STATEMENT,
            "policy_id": _POLICY_ID,
            "policy_revision": _POLICY_REVISION,
            "reviewers": projections,
        }
    )


def acceptance_context_digest(
    acceptance: Mapping[str, Any],
    *,
    roster_digest: str | None = None,
) -> str:
    """Digest acceptance state outside one reviewer object."""

    reviewers = acceptance.get("reviewers")
    if not isinstance(reviewers, list):
        fail("acceptance.reviewers must be an array")
    digest = roster_digest or review_set_digest(reviewers)
    limitations = acceptance.get("limitations", [])
    if not isinstance(limitations, list):
        fail("acceptance.limitations must be an array")
    return canonical_digest(
        {
            "statement_type": _ACCEPTANCE_CONTEXT_STATEMENT,
            "policy_id": _POLICY_ID,
            "policy_revision": _POLICY_REVISION,
            "state": acceptance.get("state"),
            "reviewed_at": acceptance.get("reviewed_at"),
            "decision_reference": acceptance.get("decision_reference"),
            "limitations": limitations,
            "review_set_digest": digest,
        }
    )


def _submission_contract_for_authority(
    raw: Any,
    *,
    index: int,
    contract: Mapping[str, Any],
    claim_scopes: Mapping[str, Mapping[str, list[str]]],
) -> dict[str, Any]:
    label = f"submissions[{index}]"
    if not isinstance(raw, dict):
        fail(f"{label} must be an object")
    gap_id = require_string(
        raw.get("gap_id"),
        label=f"{label}.gap_id",
        maximum=20,
    )
    issuer = raw.get("issuer")
    if not isinstance(issuer, dict):
        fail(f"{label}.issuer must be an object")
    authority_class = require_string(
        issuer.get("authority_class"),
        label=f"{label}.issuer.authority_class",
        maximum=80,
    )
    gap_scopes = claim_scopes.get(gap_id)
    if gap_scopes is None or authority_class not in gap_scopes:
        fail(
            f"{label} issuer authority {authority_class} cannot attest "
            f"{gap_id}"
        )
    required = list(gap_scopes[authority_class])
    claims = raw.get("claims")
    if not isinstance(claims, dict):
        fail(f"{label}.claims must be an object")
    supplied = set(claims)
    required_set = set(required)
    missing = sorted(required_set - supplied)
    unauthorized = sorted(supplied - required_set)
    if missing:
        fail(
            f"{label} is missing authority-scoped claims for "
            f"{authority_class}: {missing}"
        )
    if unauthorized:
        fail(
            f"{label} asserts claims outside authority scope for "
            f"{authority_class}: {unauthorized}"
        )

    scoped_contract = dict(contract)
    required_claims = dict(contract["required_claims"])
    required_claims[gap_id] = required
    scoped_contract["required_claims"] = required_claims
    return scoped_contract


def _issuer_authority_coverage(
    submissions: Sequence[Mapping[str, Any]],
    *,
    contract: Mapping[str, Any],
) -> tuple[dict[str, dict[str, list[str]]], dict[str, list[str]]]:
    raw_required = contract.get("authority_classes")
    if not isinstance(raw_required, dict):
        fail("evidence contract authority_classes must be an object")

    coverage: dict[str, dict[str, list[str]]] = {}
    seen_keys: dict[str, set[str]] = {}
    seen_identities: dict[str, set[tuple[str, str]]] = {}

    for index, submission in enumerate(submissions):
        label = f"validated_submissions[{index}]"
        gap_id = require_string(
            submission.get("gap_id"),
            label=f"{label}.gap_id",
            maximum=20,
        )
        authority_class = require_string(
            submission.get("authority_class"),
            label=f"{label}.authority_class",
            maximum=80,
        )
        key_id = require_string(
            submission.get("issuer_key_id"),
            label=f"{label}.issuer_key_id",
            maximum=500,
        )
        identity = require_string(
            submission.get("issuer_identity"),
            label=f"{label}.issuer_identity",
            maximum=300,
        )
        organization = require_string(
            submission.get("issuer_organization"),
            label=f"{label}.issuer_organization",
            maximum=300,
        )

        gap_keys = seen_keys.setdefault(gap_id, set())
        if key_id in gap_keys:
            fail(
                f"gap {gap_id} reuses issuer key {key_id}; "
                "one key cannot satisfy multiple authority seats"
            )
        gap_keys.add(key_id)

        identity_key = (identity, organization)
        gap_identities = seen_identities.setdefault(gap_id, set())
        if identity_key in gap_identities:
            fail(
                f"gap {gap_id} reuses issuer identity {identity!r} from "
                f"{organization!r}; authority seats require distinct "
                "identity/organization pairs"
            )
        gap_identities.add(identity_key)

        coverage.setdefault(gap_id, {}).setdefault(
            authority_class,
            [],
        ).append(key_id)

    normalized: dict[str, dict[str, list[str]]] = {}
    missing: dict[str, list[str]] = {}
    for gap_id, required_values in raw_required.items():
        required = set(required_values)
        actual = coverage.get(gap_id, {})
        normalized[gap_id] = {
            authority: sorted(keys)
            for authority, keys in sorted(actual.items())
        }
        absent = sorted(required - set(actual))
        if absent:
            missing[gap_id] = absent

    return normalized, missing


def _validate_review_set_integrity(
    *,
    acceptance_document: Mapping[str, Any],
    acceptance_result: Mapping[str, Any],
    artifact_root: Path,
) -> dict[str, Any]:
    raw_reviewers = acceptance_document.get("reviewers")
    validated_reviewers = acceptance_result.get("reviewers")
    if not isinstance(raw_reviewers, list) or not isinstance(
        validated_reviewers,
        list,
    ):
        fail("accepted bundle reviewer state is unavailable")
    if len(raw_reviewers) != len(validated_reviewers):
        fail("accepted bundle reviewer roster changed during validation")

    expected_roster = review_set_digest(raw_reviewers)
    expected_context = acceptance_context_digest(
        acceptance_document,
        roster_digest=expected_roster,
    )
    verified_key_ids: list[str] = []

    for index, reviewer in enumerate(raw_reviewers):
        label = f"acceptance.reviewers[{index}]"
        if not isinstance(reviewer, dict):
            fail(f"{label} must be an object")
        review_uri = require_string(
            reviewer.get("review_uri"),
            label=f"{label}.review_uri",
            maximum=2000,
        )
        review_path = safe_artifact_path(
            artifact_root,
            review_uri,
            label=f"{label}.review_uri",
        )
        document = read_object(
            review_path,
            f"{label}.review_manifest",
            maximum_bytes=MAX_ARTIFACT_BYTES,
        )
        manifest = document.get("closure_manifest")
        if not isinstance(manifest, dict):
            fail(f"{label}.review lacks closure_manifest")
        require_exact_keys(
            manifest,
            required={
                "schema_version",
                "policy_id",
                "policy_revision",
                "review_set_digest",
                "acceptance_context_digest",
            },
            optional=set(),
            label=f"{label}.review.closure_manifest",
        )
        if manifest["schema_version"] != _REVIEW_MANIFEST_VERSION:
            fail(f"{label}.review closure manifest version is unsupported")
        if manifest["policy_id"] != _POLICY_ID:
            fail(f"{label}.review closure manifest policy_id drifted")
        if manifest["policy_revision"] != _POLICY_REVISION:
            fail(f"{label}.review closure manifest policy_revision drifted")
        supplied_roster = require_sha(
            manifest["review_set_digest"],
            label=f"{label}.review.closure_manifest.review_set_digest",
            width=64,
        )
        supplied_context = require_sha(
            manifest["acceptance_context_digest"],
            label=(
                f"{label}.review.closure_manifest."
                "acceptance_context_digest"
            ),
            width=64,
        )
        if supplied_roster != expected_roster:
            fail(
                f"{label}.review closure manifest does not bind the final "
                "reviewer set"
            )
        if supplied_context != expected_context:
            fail(
                f"{label}.review closure manifest does not bind the final "
                "acceptance context"
            )
        verified = validated_reviewers[index]
        if not isinstance(verified, dict):
            fail(f"{label} validated result is malformed")
        verified_key_ids.append(
            require_string(
                verified.get("key_id"),
                label=f"{label}.validated_key_id",
                maximum=500,
            )
        )

    return {
        "verified": True,
        "schema_version": _REVIEW_MANIFEST_VERSION,
        "policy_id": _POLICY_ID,
        "policy_revision": _POLICY_REVISION,
        "review_set_digest": expected_roster,
        "acceptance_context_digest": expected_context,
        "reviewer_key_ids": verified_key_ids,
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
    """Validate a bundle under the versioned G10 closure policy."""

    now = now or datetime.now(timezone.utc)
    contract = read_object(CONTRACT_PATH, "external evidence contract")
    claim_scopes = _validate_contract_policy(contract)
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
    if not isinstance(raw_submissions, list) or not (
        1 <= len(raw_submissions) <= 64
    ):
        fail("bundle.submissions must be a non-empty bounded array")
    seen_artifacts: set[str] = set()
    submissions: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_submissions):
        scoped_contract = _submission_contract_for_authority(
            raw,
            index=index,
            contract=contract,
            claim_scopes=claim_scopes,
        )
        submissions.append(
            validate_submission(
                raw,
                bundle=bundle,
                index=index,
                contract=scoped_contract,
                artifact_root=artifact_root,
                seen_artifacts=seen_artifacts,
                registry=registry,
                candidate_collected_at=candidate_collected_at,
                now=now,
                openssl_binary=openssl_binary,
            )
        )

    submitted_gaps = {item["gap_id"] for item in submissions}
    required_gaps = set(contract["allowed_gap_ids"])
    missing_gaps = sorted(required_gaps - submitted_gaps)
    authority_coverage, missing_authority_classes = (
        _issuer_authority_coverage(
            submissions,
            contract=contract,
        )
    )
    if require_complete and missing_gaps:
        fail(f"complete bundle is missing authority-owned gaps: {missing_gaps}")
    if require_complete and missing_authority_classes:
        fail(
            "complete bundle lacks required issuer authority classes: "
            f"{missing_authority_classes}"
        )

    acceptance_document = bundle["acceptance"]
    acceptance = validate_acceptance(
        acceptance_document,
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

    complete_authority_set = not missing_gaps and not missing_authority_classes
    review_set_integrity: dict[str, Any] = {
        "verified": False,
        "schema_version": _REVIEW_MANIFEST_VERSION,
        "policy_id": _POLICY_ID,
        "policy_revision": _POLICY_REVISION,
        "review_set_digest": None,
        "acceptance_context_digest": None,
        "reviewer_key_ids": [],
    }
    if acceptance["state"] == "accepted":
        review_set_integrity = _validate_review_set_integrity(
            acceptance_document=acceptance_document,
            acceptance_result=acceptance,
            artifact_root=artifact_root,
        )

    eligible = complete_authority_set and acceptance["state"] in {
        "eligible_for_review",
        "accepted",
    }
    closed = (
        eligible
        and acceptance["state"] == "accepted"
        and review_set_integrity["verified"]
    )
    return {
        "ok": True,
        "contract_id": contract["contract_id"],
        "contract_revision": contract["contract_revision"],
        "complete_closure_policy": {
            "policy_id": _POLICY_ID,
            "policy_revision": _POLICY_REVISION,
        },
        "signature_profile": contract["signature_profile"],
        "trust_registry": {
            "registry_id": registry.registry_id,
            "sha256": registry.digest,
            "external_pin_verified": True,
            "expires_at": registry.expires_at.isoformat(),
        },
        "candidate": candidate,
        "submitted_gaps": sorted(submitted_gaps),
        "missing_gaps": missing_gaps,
        "issuer_claim_scopes": claim_scopes,
        "issuer_authority_coverage": authority_coverage,
        "missing_issuer_authority_classes": missing_authority_classes,
        "artifact_count": len(seen_artifacts),
        "submissions": submissions,
        "acceptance": acceptance,
        "review_set_integrity": review_set_integrity,
        "eligible_for_review": eligible,
        "all_authority_owned_gaps_closed": closed,
    }
