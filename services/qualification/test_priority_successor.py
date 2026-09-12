"""Inert local regressions for the PR #126 successor pointer.

These verify the current-pointer admission boundary, not real GitHub evidence.
No fixture can satisfy the independently qualified historical baseline.
"""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from services.qualification import documentation_truth_core as truth

ROOT = Path(__file__).resolve().parents[2]


class HistoricalReadRequired(Exception):
    """Stop an inert fixture exactly where the real historical read is required."""


class PrioritySuccessorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.head = "1" * 40
        self.tree = "2" * 40
        self.pull = {
            "number": 126, "state": "open", "merged_at": None,
            "head": {"ref": "codex/hepta-priority-execution-20260912", "sha": self.head,
                     "repo": {"full_name": truth.EXPECTED_REPOSITORY}},
            "base": {"ref": "codex/hepta-identity-migration-20260910"},
        }
        self.commit = {"sha": self.head, "commit": {"tree": {"sha": self.tree}}}
        self.observed = []

    def read(self, path: str, *, token: str):
        self.observed.append(path)
        prefix = f"/repos/{truth.EXPECTED_REPOSITORY}"
        if path == prefix + "/pulls/126":
            return copy.deepcopy(self.pull)
        if path == prefix + "/commits/" + self.head:
            return copy.deepcopy(self.commit)
        if path == prefix + "/commits/" + truth.PINNED_BASELINE["commit"]:
            raise HistoricalReadRequired
        raise AssertionError("unexpected qualification read")

    def verify(self, execution_head: str | None = None) -> None:
        environment = {
            "GITHUB_REPOSITORY": truth.EXPECTED_REPOSITORY,
            "SOURCE_HEAD_SHA": self.head if execution_head is None else execution_head,
        }
        with patch.dict("os.environ", environment, clear=True), patch.object(
            truth, "_stable_api_object", side_effect=self.read
        ):
            truth.verify_github_baseline(token="inert-local-fixture")

    def test_canonical_constants_and_machine_pointer_agree(self) -> None:
        project = json.loads((ROOT / "docs/PROJECT_STATE.json").read_text())
        authority = project["source_authority"]
        self.assertEqual(truth.EXPECTED_SUCCESSOR_PULL_REQUEST, 126)
        self.assertEqual(authority["pull_request"], 126)
        self.assertEqual(authority["branch"], truth.EXPECTED_SUCCESSOR_BRANCH)
        self.assertEqual(authority["base_branch"], truth.EXPECTED_SUCCESSOR_BASE_BRANCH)
        self.assertFalse(authority["self_attested_sha_is_authoritative"])
        self.assertTrue(authority["historical_artifact_does_not_attest_later_push"])
        truth._validate_pinned_baseline(project["last_qualified_source"])
        truth._validate_successor(project["current_successor"])

    def test_current_prose_names_the_same_candidate(self) -> None:
        for path in ("README.md", "docs/CURRENT_STATE.md"):
            text = (ROOT / path).read_text()
            self.assertIn("open PR #126", text)
            self.assertIn(truth.EXPECTED_SUCCESSOR_BRANCH, text)
            self.assertIn(truth.EXPECTED_SUCCESSOR_BASE_BRANCH, text)
            self.assertIn(truth.PINNED_BASELINE["artifact_zip_sha256"], text)

    def test_valid_current_identity_still_requires_historical_evidence(self) -> None:
        with self.assertRaises(HistoricalReadRequired):
            self.verify()
        self.assertEqual(len(self.observed), 3)

    def test_predecessor_pull_number_is_not_current_identity(self) -> None:
        self.pull["number"] = 125
        with self.assertRaisesRegex(truth.DocumentationTruthError, "pull-request identity"):
            self.verify()
        self.assertEqual(len(self.observed), 1)

    def test_predecessor_head_branch_is_rejected(self) -> None:
        self.pull["head"]["ref"] = "codex/hepta-identity-migration-20260910"
        with self.assertRaisesRegex(truth.DocumentationTruthError, "head branch"):
            self.verify()

    def test_predecessor_base_branch_is_rejected(self) -> None:
        self.pull["base"]["ref"] = "codex/hepta-main-convergence-20260909-v2"
        with self.assertRaisesRegex(truth.DocumentationTruthError, "base branch"):
            self.verify()

    def test_wrong_executing_head_is_rejected(self) -> None:
        with self.assertRaisesRegex(truth.DocumentationTruthError, "executing source head"):
            self.verify(execution_head="3" * 40)
        self.assertEqual(len(self.observed), 1)

    def test_foreign_repository_is_rejected(self) -> None:
        self.pull["head"]["repo"]["full_name"] = "untrusted/repository"
        with self.assertRaisesRegex(truth.DocumentationTruthError, "head repository"):
            self.verify()

    def test_closed_candidate_is_rejected(self) -> None:
        self.pull["state"] = "closed"
        with self.assertRaisesRegex(truth.DocumentationTruthError, "open and unmerged"):
            self.verify()

    def test_merged_candidate_is_rejected(self) -> None:
        self.pull["merged_at"] = "2026-09-12T00:00:00Z"
        with self.assertRaisesRegex(truth.DocumentationTruthError, "open and unmerged"):
            self.verify()

    def test_wrong_commit_identity_is_rejected(self) -> None:
        self.commit["sha"] = "4" * 40
        with self.assertRaisesRegex(truth.DocumentationTruthError, "commit identity"):
            self.verify()

    def test_invalid_tree_is_not_evidence(self) -> None:
        self.commit["commit"]["tree"]["sha"] = "not-a-git-tree"
        with self.assertRaisesRegex(truth.DocumentationTruthError, "lowercase 40-hex"):
            self.verify()

    def test_successor_cannot_inherit_qualification(self) -> None:
        project = json.loads((ROOT / "docs/PROJECT_STATE.json").read_text())
        for key in ("qualified", "ci_qualified", "integration_qualified",
                    "physical_device_qualified", "pilot_qualified", "released",
                    "evidence_transfer_allowed"):
            changed = copy.deepcopy(project["current_successor"])
            changed[key] = True
            with self.subTest(key=key), self.assertRaises(truth.DocumentationTruthError):
                truth._validate_successor(changed)

    def test_expired_artifact_is_not_accepted_by_core(self) -> None:
        # The production verifier still checks expiry; exercise that branch with
        # the established live-binding suite in full CI. Here assert the source
        # check is retained, not that an inert fixture has an authentic artifact.
        source = (ROOT / "services/qualification/documentation_truth_core.py").read_text()
        self.assertIn('if artifact.get("expired") is not False:', source)
        self.assertIn('fail("qualified Artifact is expired")', source)


if __name__ == "__main__":
    unittest.main()
