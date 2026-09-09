from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from services.qualification.governance import (
    CANONICAL_REQUIRED_CONTEXTS,
    GITHUB_ACTIONS_APP_ID,
    evaluate_branch_protection,
)
from tools import repository_governance as governance_cli


class GovernanceTest(unittest.TestCase):
    def contract(self) -> dict[str, object]:
        return {
            "required_status_checks": {
                "strict": True,
                "contexts": list(CANONICAL_REQUIRED_CONTEXTS),
                "checks": [
                    {
                        "context": context,
                        "app_id": GITHUB_ACTIONS_APP_ID,
                    }
                    for context in CANONICAL_REQUIRED_CONTEXTS
                ],
            },
            "enforce_admins": True,
            "required_pull_request_reviews": {
                "dismiss_stale_reviews": True,
                "require_code_owner_reviews": True,
                "required_approving_review_count": 1,
                "require_last_push_approval": True,
                "bypass_pull_request_allowances": {
                    "users": [],
                    "teams": [],
                    "apps": [],
                },
            },
            "restrictions": None,
            "required_linear_history": True,
            "allow_force_pushes": False,
            "allow_deletions": False,
            "block_creations": False,
            "required_conversation_resolution": True,
            "lock_branch": False,
            "allow_fork_syncing": False,
        }

    def snapshot(self) -> dict[str, object]:
        contract = self.contract()
        expected_status = contract["required_status_checks"]
        assert isinstance(expected_status, dict)
        checks = deepcopy(expected_status["checks"])
        return {
            "required_status_checks": {
                "strict": True,
                "contexts": list(CANONICAL_REQUIRED_CONTEXTS),
                "checks": checks,
            },
            "required_pull_request_reviews": {
                "required_approving_review_count": 1,
                "dismiss_stale_reviews": True,
                "require_code_owner_reviews": True,
                "require_last_push_approval": True,
                "bypass_pull_request_allowances": {
                    "users": [],
                    "teams": [],
                    "apps": [],
                },
            },
            "enforce_admins": {"enabled": True},
            "restrictions": None,
            "required_linear_history": {"enabled": True},
            "allow_force_pushes": {"enabled": False},
            "allow_deletions": {"enabled": False},
            "block_creations": {"enabled": False},
            "required_conversation_resolution": {"enabled": True},
            "lock_branch": {"enabled": False},
            "allow_fork_syncing": {"enabled": False},
        }

    def test_expected_complete_protection_passes(self) -> None:
        result = evaluate_branch_protection(self.snapshot(), self.contract())
        self.assertTrue(result.passed, result.missing)
        self.assertEqual(result.missing, ())

    def test_empty_bypass_readback_may_be_omitted(self) -> None:
        snapshot = self.snapshot()
        reviews = snapshot["required_pull_request_reviews"]
        assert isinstance(reviews, dict)
        reviews.pop("bypass_pull_request_allowances")
        result = evaluate_branch_protection(snapshot, self.contract())
        self.assertTrue(result.passed, result.missing)

    def test_contract_must_explicitly_clear_bypass(self) -> None:
        contract = self.contract()
        reviews = contract["required_pull_request_reviews"]
        assert isinstance(reviews, dict)
        reviews.pop("bypass_pull_request_allowances")
        result = evaluate_branch_protection(self.snapshot(), contract)
        self.assertFalse(result.passed)
        self.assertEqual(result.missing, ("contract_shape",))

    def test_unprotected_snapshot_fails_closed(self) -> None:
        result = evaluate_branch_protection({}, self.contract())
        self.assertFalse(result.passed)
        self.assertIn("required_contexts", result.missing)
        self.assertIn("status_check_app_binding", result.missing)
        self.assertIn("last_push_approval", result.missing)
        self.assertIn("admins_enforced", result.missing)

    def test_required_contexts_are_exact_and_unique(self) -> None:
        for mutate in ("extra", "missing", "duplicate"):
            with self.subTest(mutate=mutate):
                snapshot = self.snapshot()
                status = snapshot["required_status_checks"]
                assert isinstance(status, dict)
                contexts = status["contexts"]
                assert isinstance(contexts, list)
                if mutate == "extra":
                    contexts.append("unreviewed-extra-check")
                elif mutate == "missing":
                    contexts.pop()
                else:
                    contexts.append(contexts[0])
                result = evaluate_branch_protection(snapshot, self.contract())
                self.assertFalse(result.passed)
                self.assertIn("required_contexts", result.missing)

    def test_status_checks_bind_exactly_to_github_actions_app(self) -> None:
        mutations = ("missing", "wildcard", "null", "wrong", "duplicate")
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                snapshot = self.snapshot()
                status = snapshot["required_status_checks"]
                assert isinstance(status, dict)
                checks = status["checks"]
                assert isinstance(checks, list)
                if mutate == "missing":
                    status.pop("checks")
                elif mutate == "wildcard":
                    checks[0]["app_id"] = -1
                elif mutate == "null":
                    checks[0]["app_id"] = None
                elif mutate == "wrong":
                    checks[0]["app_id"] = GITHUB_ACTIONS_APP_ID + 1
                else:
                    checks.append(deepcopy(checks[0]))
                result = evaluate_branch_protection(snapshot, self.contract())
                self.assertFalse(result.passed)
                self.assertIn("status_check_app_binding", result.missing)

    def test_review_controls_fail_closed(self) -> None:
        mutations = (
            "required_approving_review_count",
            "dismiss_stale_reviews",
            "require_code_owner_reviews",
            "require_last_push_approval",
            "bypass_pull_request_allowances",
        )
        for field in mutations:
            with self.subTest(field=field):
                snapshot = self.snapshot()
                reviews = snapshot["required_pull_request_reviews"]
                assert isinstance(reviews, dict)
                if field == "required_approving_review_count":
                    reviews[field] = 0
                elif field == "bypass_pull_request_allowances":
                    reviews[field] = {
                        "users": [{"login": "bypass-user"}],
                        "teams": [],
                        "apps": [],
                    }
                else:
                    reviews[field] = False
                result = evaluate_branch_protection(snapshot, self.contract())
                self.assertFalse(result.passed)

    def test_bypass_allowances_reject_type_confusion(self) -> None:
        for invalid in (None, "", {}, 0, False):
            with self.subTest(invalid=invalid):
                snapshot = self.snapshot()
                reviews = snapshot["required_pull_request_reviews"]
                assert isinstance(reviews, dict)
                reviews["bypass_pull_request_allowances"] = {
                    "users": invalid,
                    "teams": [],
                    "apps": [],
                }
                result = evaluate_branch_protection(
                    snapshot,
                    self.contract(),
                )
                self.assertFalse(result.passed)
                self.assertIn("no_pull_request_bypass", result.missing)

    def test_every_top_level_policy_field_is_enforced(self) -> None:
        mutations = {
            "enforce_admins": {"enabled": False},
            "restrictions": {"users": [], "teams": [], "apps": []},
            "required_linear_history": {"enabled": False},
            "allow_force_pushes": {"enabled": True},
            "allow_deletions": {"enabled": True},
            "block_creations": {"enabled": True},
            "required_conversation_resolution": {"enabled": False},
            "lock_branch": {"enabled": True},
            "allow_fork_syncing": {"enabled": True},
        }
        for field, value in mutations.items():
            with self.subTest(field=field):
                snapshot = self.snapshot()
                snapshot[field] = value
                result = evaluate_branch_protection(snapshot, self.contract())
                self.assertFalse(result.passed)

    def test_weakened_or_extended_contract_fails_closed(self) -> None:
        contracts: list[dict[str, object]] = []
        missing = self.contract()
        missing.pop("enforce_admins")
        contracts.append(missing)

        extended = self.contract()
        extended["unvalidated_future_field"] = True
        contracts.append(extended)

        legacy_contexts = self.contract()
        status = legacy_contexts["required_status_checks"]
        assert isinstance(status, dict)
        status["contexts"] = [
            item["context"] for item in status.pop("checks")
        ]
        contracts.append(legacy_contexts)

        weakened = self.contract()
        weakened["enforce_admins"] = False
        contracts.append(weakened)

        wrong_app = self.contract()
        status = wrong_app["required_status_checks"]
        assert isinstance(status, dict)
        checks = status["checks"]
        assert isinstance(checks, list)
        checks[0]["app_id"] = -1
        contracts.append(wrong_app)

        for index, contract in enumerate(contracts):
            with self.subTest(index=index):
                result = evaluate_branch_protection(self.snapshot(), contract)
                self.assertFalse(result.passed)
                self.assertEqual(result.missing, ("contract_shape",))

    def test_committed_contract_matches_canonical_fixture(self) -> None:
        root = Path(__file__).resolve().parents[2]
        committed = governance_cli.read_json_object(
            root / "contracts/main-branch-protection-v1.json",
            "committed_contract",
        )
        self.assertEqual(committed, self.contract())
        result = evaluate_branch_protection(self.snapshot(), committed)
        self.assertTrue(result.passed, result.missing)

    def test_api_payload_rejects_weakened_contract(self) -> None:
        contract = self.contract()
        contract["enforce_admins"] = False
        with self.assertRaises(governance_cli.GovernanceInputError):
            governance_cli.branch_protection_payload(contract)

    def test_apply_rejects_noncanonical_contract_before_network(self) -> None:
        contract = self.contract()
        contract["enforce_admins"] = False
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "weakened.json"
            path.write_text(json.dumps(contract), encoding="utf-8")
            with patch.dict(
                "os.environ",
                {"HEPTA_REPO_ADMIN_TOKEN": "redacted-test-token"},
            ):
                with patch(
                    "sys.argv",
                    [
                        "repository_governance.py",
                        "--apply",
                        "--contract",
                        str(path),
                    ],
                ):
                    with patch.object(
                        governance_cli,
                        "request_json",
                    ) as request:
                        self.assertEqual(governance_cli.main(), 2)
                        request.assert_not_called()

    def test_noncanonical_target_is_rejected_before_network(self) -> None:
        with patch(
            "sys.argv",
            [
                "repository_governance.py",
                "--repo",
                "other/repository",
                "--branch",
                "main",
            ],
        ):
            with patch.object(
                governance_cli,
                "request_json",
            ) as request:
                self.assertEqual(governance_cli.main(), 2)
                request.assert_not_called()

    def test_api_payload_uses_checks_without_redundant_contexts(self) -> None:
        contract = self.contract()
        payload = governance_cli.branch_protection_payload(contract)
        original_status = contract["required_status_checks"]
        payload_status = payload["required_status_checks"]
        assert isinstance(original_status, dict)
        assert isinstance(payload_status, dict)
        self.assertIn("contexts", original_status)
        self.assertNotIn("contexts", payload_status)
        self.assertEqual(payload_status["checks"], original_status["checks"])

    def test_apply_cannot_validate_an_offline_snapshot(self) -> None:
        with patch(
            "sys.argv",
            [
                "repository_governance.py",
                "--apply",
                "--snapshot",
                "stale.json",
            ],
        ):
            with self.assertRaises(SystemExit) as raised:
                governance_cli.main()
        self.assertEqual(raised.exception.code, 2)

    def test_strict_json_rejects_duplicate_and_nonfinite_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixtures = {
                "duplicate.json": b'{"strict":true,"strict":false}',
                "nan.json": b'{"value":NaN}',
                "bom.json": b'\xef\xbb\xbf{"value":1}',
            }
            for name, raw in fixtures.items():
                with self.subTest(name=name):
                    path = root / name
                    path.write_bytes(raw)
                    with self.assertRaises(governance_cli.GovernanceInputError):
                        governance_cli.read_json_object(path, name)


if __name__ == "__main__":
    unittest.main()
