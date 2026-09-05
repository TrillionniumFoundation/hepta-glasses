"""Translate an authenticated G10 closure result into product gates."""

from __future__ import annotations

from typing import Any, Mapping

REQUIRED_AUTHORITY_GAPS = frozenset(
    {
        "HG-0010", "HG-0011", "HG-0012", "HG-0013",
        "HG-0014", "HG-0015", "HG-0016", "HG-0017",
        "HG-0018", "HG-0021", "HG-0022", "HG-0044",
    }
)
EXTERNAL_POLICY_ID = "hepta-external-complete-closure-v1"
EXTERNAL_POLICY_REVISION = "2026-09-02-g10-quorum-1"


def authenticated_product_checks(
    *,
    source: Mapping[str, Any],
    external_evidence_result: Mapping[str, Any] | None,
    required_authority_gaps: frozenset[str] = REQUIRED_AUTHORITY_GAPS,
    policy_id: str = EXTERNAL_POLICY_ID,
    policy_revision: str = EXTERNAL_POLICY_REVISION,
) -> dict[str, bool]:
    """Require exact identity, policy, external trust pin, quorum, and review."""
    result = (
        external_evidence_result
        if isinstance(external_evidence_result, Mapping)
        else {}
    )
    candidate = result.get("candidate")
    candidate = candidate if isinstance(candidate, Mapping) else {}
    registry = result.get("trust_registry")
    registry = registry if isinstance(registry, Mapping) else {}
    policy = result.get("complete_closure_policy")
    policy = policy if isinstance(policy, Mapping) else {}
    review_set = result.get("review_set_integrity")
    review_set = review_set if isinstance(review_set, Mapping) else {}
    acceptance = result.get("acceptance")
    acceptance = acceptance if isinstance(acceptance, Mapping) else {}
    submitted = result.get("submitted_gaps")
    submitted_set = (
        {value for value in submitted if isinstance(value, str)}
        if isinstance(submitted, list)
        else set()
    )
    missing = result.get("missing_gaps")
    missing_classes = result.get("missing_issuer_authority_classes")

    identity_bound = (
        candidate.get("repository") == "TrillionniumFoundation/hepta-glasses"
        and candidate.get("commit") == source.get("commit")
        and candidate.get("tree") == source.get("tree")
    )
    policy_bound = (
        policy.get("policy_id") == policy_id
        and policy.get("policy_revision") == policy_revision
    )
    complete = (
        result.get("ok") is True
        and result.get("all_authority_owned_gaps_closed") is True
        and missing == []
        and missing_classes == {}
        and required_authority_gaps.issubset(submitted_set)
    )
    independently_accepted = (
        acceptance.get("state") == "accepted"
        and review_set.get("verified") is True
    )
    externally_pinned = registry.get("external_pin_verified") is True
    authenticated = (
        identity_bound
        and policy_bound
        and complete
        and independently_accepted
        and externally_pinned
    )

    def gap(gap_id: str) -> bool:
        return authenticated and gap_id in submitted_set

    return {
        "authenticated_external_evidence": authenticated,
        "external_candidate_identity": identity_bound,
        "external_policy_binding": policy_bound,
        "external_registry_pin": externally_pinned,
        "external_review_set": independently_accepted,
        "all_authority_owned_gaps": complete,
        "branch_protected": gap("HG-0017"),
        "branch_reviews": gap("HG-0017") and gap("HG-0044"),
        "branch_force_push_disabled": gap("HG-0017"),
        "branch_required_checks": gap("HG-0017") and gap("HG-0044"),
        "android_device_qualification": gap("HG-0010"),
        "ios_device_qualification": gap("HG-0010"),
        "production_model_provider": gap("HG-0014"),
        "production_identity": gap("HG-0015"),
        "production_attestation": gap("HG-0015"),
        "production_speech": gap("HG-0018"),
        "production_realtime_oauth": gap("HG-0021"),
        "production_capabilities": gap("HG-0022"),
        "vendor_firmware_authority": gap("HG-0016"),
        "security_review": gap("HG-0011"),
        "privacy_review": gap("HG-0011"),
        "legal_review": gap("HG-0011"),
        "accessibility_review": gap("HG-0011"),
        "safety_review": gap("HG-0011"),
        "kill_switch_drill": gap("HG-0012"),
        "rollback_drill": gap("HG-0012"),
        "credential_rotation_drill": gap("HG-0013"),
        "android_signing": gap("HG-0012"),
        "ios_signing": gap("HG-0012"),
        "release_provenance": gap("HG-0012"),
        "release_attestation_verified": gap("HG-0012"),
        "pilot_cohort": gap("HG-0012"),
        "pilot_crash_free": gap("HG-0012"),
        "pilot_duplicate_effects": gap("HG-0012"),
    }
