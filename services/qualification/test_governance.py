from __future__ import annotations

import unittest

from services.qualification.governance import evaluate_branch_protection


class GovernanceTest(unittest.TestCase):
    def contract(self) -> dict[str, object]:
        return {
            "required_status_checks": {
                "contexts": [
                    "flutter",
                    "repository-contracts",
                    "secret-and-boundary-scan",
                    "source-evidence",
                ]
            },
            "required_pull_request_reviews": {
                "required_approving_review_count": 1
            },
        }

    def test_expected_protection_passes(self) -> None:
        snapshot = {
            "required_status_checks": {
                "strict": True,
                "contexts": self.contract()["required_status_checks"]["contexts"],
            },
            "required_pull_request_reviews": {
                "required_approving_review_count": 1,
                "dismiss_stale_reviews": True,
                "require_code_owner_reviews": True,
            },
            "enforce_admins": {"enabled": True},
            "required_linear_history": {"enabled": True},
            "allow_force_pushes": {"enabled": False},
            "allow_deletions": {"enabled": False},
            "required_conversation_resolution": {"enabled": True},
        }
        result = evaluate_branch_protection(snapshot, self.contract())
        self.assertTrue(result.passed, result.missing)

    def test_unprotected_snapshot_fails(self) -> None:
        result = evaluate_branch_protection({}, self.contract())
        self.assertFalse(result.passed)
        self.assertIn("required_contexts", result.missing)


if __name__ == "__main__":
    unittest.main()
