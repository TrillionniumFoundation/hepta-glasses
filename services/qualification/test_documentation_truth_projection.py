from __future__ import annotations

import copy
import unittest

from services.qualification import documentation_truth as truth
from services.qualification import test_documentation_truth_live as live_fixture


class MutableWorkflowRunProjectionTests(unittest.TestCase):
    """Exercise the closed-PR mutation observed from GitHub's run endpoint."""

    def setUp(self) -> None:
        self.fixture = live_fixture.LiveQualificationBindingTests(
            methodName="test_complete_binding_is_accepted"
        )
        self.fixture.setUp()
        pull = self.fixture.payloads[self.fixture.paths["pull"]]
        pull["head"]["ref"] = truth.PINNED_BASELINE_HEAD_BRANCH
        run = self.fixture.payloads[self.fixture.paths["run"]]
        run["head_branch"] = truth.PINNED_BASELINE_HEAD_BRANCH

    def test_exact_empty_projection_is_accepted(self) -> None:
        run = self.fixture.payloads[self.fixture.paths["run"]]
        run["pull_requests"] = []
        result = self.fixture.verify()
        self.assertEqual(result["run_id"], truth.PINNED_BASELINE["workflow_run_id"])
        self.assertTrue(result["stable_double_reads"])

    def test_empty_projection_with_wrong_run_branch_is_rejected(self) -> None:
        run = self.fixture.payloads[self.fixture.paths["run"]]
        run["pull_requests"] = []
        run["head_branch"] = "attacker/substitution"
        with self.assertRaisesRegex(
            truth.DocumentationTruthError,
            "lacks exact frozen run/PR anchors",
        ):
            self.fixture.verify()

    def test_empty_projection_with_wrong_pull_branch_is_rejected(self) -> None:
        run = self.fixture.payloads[self.fixture.paths["run"]]
        run["pull_requests"] = []
        pull = self.fixture.payloads[self.fixture.paths["pull"]]
        pull["head"]["ref"] = "attacker/substitution"
        with self.assertRaisesRegex(
            truth.DocumentationTruthError,
            "lacks exact frozen run/PR anchors",
        ):
            self.fixture.verify()

    def test_empty_projection_with_wrong_event_is_rejected(self) -> None:
        run = self.fixture.payloads[self.fixture.paths["run"]]
        run["pull_requests"] = []
        run["event"] = "workflow_dispatch"
        with self.assertRaisesRegex(
            truth.DocumentationTruthError,
            "lacks exact frozen run/PR anchors",
        ):
            self.fixture.verify()

    def test_conflicting_nonempty_projection_is_rejected(self) -> None:
        run = self.fixture.payloads[self.fixture.paths["run"]]
        run["pull_requests"][0]["number"] += 1
        with self.assertRaisesRegex(
            truth.DocumentationTruthError,
            "ambiguous or conflicting",
        ):
            self.fixture.verify()

    def test_ambiguous_nonempty_projection_is_rejected(self) -> None:
        run = self.fixture.payloads[self.fixture.paths["run"]]
        conflicting = copy.deepcopy(run["pull_requests"][0])
        conflicting["number"] += 1
        run["pull_requests"].append(conflicting)
        with self.assertRaisesRegex(
            truth.DocumentationTruthError,
            "ambiguous or conflicting",
        ):
            self.fixture.verify()

    def test_malformed_projection_is_rejected(self) -> None:
        run = self.fixture.payloads[self.fixture.paths["run"]]
        run["pull_requests"] = None
        with self.assertRaisesRegex(
            truth.DocumentationTruthError,
            "projection is not a list",
        ):
            self.fixture.verify()


if __name__ == "__main__":
    unittest.main()
