"""Repository branch-protection contract evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


GITHUB_ACTIONS_APP_ID = 15368
CANONICAL_REQUIRED_CONTEXTS = (
    "repository-contracts",
    "flutter",
    "android-native",
    "ios-native",
    "native-sanitizers",
    "secret-and-boundary-scan",
    "source-evidence",
)
_CONTRACT_KEYS = frozenset(
    {
        "required_status_checks",
        "enforce_admins",
        "required_pull_request_reviews",
        "restrictions",
        "required_linear_history",
        "allow_force_pushes",
        "allow_deletions",
        "block_creations",
        "required_conversation_resolution",
        "lock_branch",
        "allow_fork_syncing",
    }
)
_STATUS_KEYS = frozenset({"strict", "contexts", "checks"})
_REVIEW_KEYS = frozenset(
    {
        "dismiss_stale_reviews",
        "require_code_owner_reviews",
        "required_approving_review_count",
        "require_last_push_approval",
        "bypass_pull_request_allowances",
    }
)
_ACTOR_ALLOWANCE_KEYS = frozenset({"users", "teams", "apps"})


@dataclass(frozen=True)
class GovernanceResult:
    passed: bool
    checks: Mapping[str, bool]

    @property
    def missing(self) -> tuple[str, ...]:
        return tuple(sorted(name for name, value in self.checks.items() if not value))


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> Sequence[Any]:
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return value
    return ()


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _enabled(snapshot: Mapping[str, Any], field: str) -> bool | None:
    value = snapshot.get(field)
    if not isinstance(value, Mapping):
        return None
    enabled = value.get("enabled")
    return enabled if isinstance(enabled, bool) else None


def _string_tuple(value: Any) -> tuple[str, ...] | None:
    values = _sequence(value)
    if not all(isinstance(item, str) and item for item in values):
        return None
    return tuple(values)


def _status_bindings(value: Any) -> tuple[tuple[str, int], ...] | None:
    result: list[tuple[str, int]] = []
    for item in _sequence(value):
        if not isinstance(item, Mapping):
            return None
        if set(item) != {"context", "app_id"}:
            return None
        context = item.get("context")
        app_id = item.get("app_id")
        if not isinstance(context, str) or not context or not _is_int(app_id):
            return None
        result.append((context, app_id))
    return tuple(result)


def _empty_actor_allowances(value: Any, *, allow_absent: bool) -> bool:
    if value is None and allow_absent:
        return True
    if not isinstance(value, Mapping) or set(value) != _ACTOR_ALLOWANCE_KEYS:
        return False
    for key in _ACTOR_ALLOWANCE_KEYS:
        actors = value.get(key)
        if not isinstance(actors, Sequence) or isinstance(
            actors, (str, bytes, bytearray)
        ):
            return False
        if len(actors) != 0:
            return False
    return True


def is_canonical_branch_protection_contract(
    contract: Mapping[str, Any],
) -> bool:
    if set(contract) != _CONTRACT_KEYS:
        return False

    status = _mapping(contract.get("required_status_checks"))
    if set(status) != _STATUS_KEYS or status.get("strict") is not True:
        return False
    contract_contexts = _string_tuple(status.get("contexts"))
    if contract_contexts != CANONICAL_REQUIRED_CONTEXTS:
        return False
    bindings = _status_bindings(status.get("checks"))
    expected_bindings = tuple(
        (context, GITHUB_ACTIONS_APP_ID)
        for context in CANONICAL_REQUIRED_CONTEXTS
    )
    if bindings != expected_bindings:
        return False

    reviews = _mapping(contract.get("required_pull_request_reviews"))
    if set(reviews) != _REVIEW_KEYS:
        return False
    review_count = reviews.get("required_approving_review_count")
    if not _is_int(review_count) or not 1 <= review_count <= 6:
        return False
    if reviews.get("dismiss_stale_reviews") is not True:
        return False
    if reviews.get("require_code_owner_reviews") is not True:
        return False
    if reviews.get("require_last_push_approval") is not True:
        return False
    if not _empty_actor_allowances(
        reviews.get("bypass_pull_request_allowances"),
        allow_absent=False,
    ):
        return False

    return (
        contract.get("enforce_admins") is True
        and contract.get("restrictions") is None
        and contract.get("required_linear_history") is True
        and contract.get("allow_force_pushes") is False
        and contract.get("allow_deletions") is False
        and contract.get("block_creations") is False
        and contract.get("required_conversation_resolution") is True
        and contract.get("lock_branch") is False
        and contract.get("allow_fork_syncing") is False
    )


def evaluate_branch_protection(
    snapshot: Mapping[str, Any], contract: Mapping[str, Any]
) -> GovernanceResult:
    """Evaluate one complete GitHub branch-protection readback fail closed."""

    if not is_canonical_branch_protection_contract(contract):
        return GovernanceResult(passed=False, checks={"contract_shape": False})

    required_status = _mapping(snapshot.get("required_status_checks"))
    expected_status = _mapping(contract["required_status_checks"])
    expected_bindings = _status_bindings(expected_status["checks"])
    assert expected_bindings is not None
    expected_contexts = tuple(context for context, _ in expected_bindings)

    actual_contexts = _string_tuple(required_status.get("contexts"))
    actual_bindings = _status_bindings(required_status.get("checks"))
    exact_contexts = (
        actual_contexts is not None
        and len(actual_contexts) == len(set(actual_contexts))
        and set(actual_contexts) == set(expected_contexts)
    )
    exact_bindings = (
        actual_bindings is not None
        and len(actual_bindings) == len(set(actual_bindings))
        and set(actual_bindings) == set(expected_bindings)
    )

    reviews = _mapping(snapshot.get("required_pull_request_reviews"))
    expected_reviews = _mapping(contract["required_pull_request_reviews"])
    actual_review_count = reviews.get("required_approving_review_count")
    expected_review_count = expected_reviews["required_approving_review_count"]

    checks = {
        "strict_status_checks": required_status.get("strict") is True,
        "required_contexts": exact_contexts,
        "status_check_app_binding": exact_bindings,
        "approving_review": (
            _is_int(actual_review_count)
            and actual_review_count == expected_review_count
        ),
        "dismiss_stale_reviews": reviews.get("dismiss_stale_reviews") is True,
        "code_owner_reviews": reviews.get("require_code_owner_reviews") is True,
        "last_push_approval": reviews.get("require_last_push_approval") is True,
        "no_pull_request_bypass": _empty_actor_allowances(
            reviews.get("bypass_pull_request_allowances"),
            allow_absent=True,
        ),
        "admins_enforced": _enabled(snapshot, "enforce_admins") is True,
        "push_restrictions_exact": snapshot.get("restrictions") is None,
        "linear_history": _enabled(snapshot, "required_linear_history") is True,
        "force_push_disabled": _enabled(snapshot, "allow_force_pushes") is False,
        "deletion_disabled": _enabled(snapshot, "allow_deletions") is False,
        "branch_creation_policy": _enabled(snapshot, "block_creations") is False,
        "conversation_resolution": (
            _enabled(snapshot, "required_conversation_resolution") is True
        ),
        "branch_lock_policy": _enabled(snapshot, "lock_branch") is False,
        "fork_sync_policy": _enabled(snapshot, "allow_fork_syncing") is False,
    }
    return GovernanceResult(passed=all(checks.values()), checks=checks)
