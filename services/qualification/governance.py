"""Repository branch-protection contract evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class GovernanceResult:
    passed: bool
    checks: Mapping[str, bool]

    @property
    def missing(self) -> tuple[str, ...]:
        return tuple(sorted(name for name, value in self.checks.items() if not value))


def evaluate_branch_protection(
    snapshot: Mapping[str, Any], contract: Mapping[str, Any]
) -> GovernanceResult:
    required_status = snapshot.get("required_status_checks")
    required_status = required_status if isinstance(required_status, Mapping) else {}
    contexts = set(required_status.get("contexts", []))
    expected_contexts = set(contract.get("required_status_checks", {}).get("contexts", []))
    reviews = snapshot.get("required_pull_request_reviews")
    reviews = reviews if isinstance(reviews, Mapping) else {}
    checks = {
        "strict_status_checks": required_status.get("strict") is True,
        "required_contexts": expected_contexts.issubset(contexts),
        "approving_review": int(reviews.get("required_approving_review_count", 0))
        >= int(contract.get("required_pull_request_reviews", {}).get("required_approving_review_count", 1)),
        "dismiss_stale_reviews": reviews.get("dismiss_stale_reviews") is True,
        "code_owner_reviews": reviews.get("require_code_owner_reviews") is True,
        "admins_enforced": snapshot.get("enforce_admins", {}).get("enabled") is True,
        "linear_history": snapshot.get("required_linear_history", {}).get("enabled") is True,
        "force_push_disabled": snapshot.get("allow_force_pushes", {}).get("enabled") is False,
        "deletion_disabled": snapshot.get("allow_deletions", {}).get("enabled") is False,
        "conversation_resolution": snapshot.get(
            "required_conversation_resolution", {}
        ).get("enabled") is True,
    }
    return GovernanceResult(passed=all(checks.values()), checks=checks)
