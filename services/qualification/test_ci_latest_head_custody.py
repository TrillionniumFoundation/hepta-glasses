from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/ci.yml"


class LatestHeadCiCustodyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.workflow = WORKFLOW.read_text(encoding="utf-8")
        self.concurrency = self.workflow.split("concurrency:\n", 1)[1].split(
            "\njobs:\n", 1
        )[0]

    def test_new_push_cancels_obsolete_run_for_same_pr_or_branch(self) -> None:
        self.assertIn(
            "group: hepta-glasses-${{ github.workflow }}-"
            "${{ github.event.pull_request.number || github.ref_name }}",
            self.concurrency,
        )
        self.assertIn("cancel-in-progress: true", self.concurrency)
        self.assertNotIn("github.event.pull_request.head.sha", self.concurrency)
        self.assertNotIn("github.sha", self.concurrency)

    def test_exact_head_identity_is_still_verified_inside_every_job(self) -> None:
        canonical_jobs = (
            "repository-contracts",
            "flutter",
            "android-native",
            "ios-native",
            "native-sanitizers",
            "secret-and-boundary-scan",
            "source-evidence",
        )
        for job in canonical_jobs:
            with self.subTest(job=job):
                self.assertIn(f"  {job}:\n", self.workflow)
        self.assertGreaterEqual(
            self.workflow.count(
                "SOURCE_HEAD_SHA: ${{ github.event.pull_request.head.sha || github.sha }}"
            ),
            len(canonical_jobs),
        )
        self.assertGreaterEqual(
            self.workflow.count(
                'run: test "$(git rev-parse HEAD)" = "$SOURCE_HEAD_SHA"'
            ),
            len(canonical_jobs),
        )

    def test_prs_and_main_each_have_one_trigger_authority(self) -> None:
        self.assertIn("  pull_request:\n", self.workflow)
        self.assertIn("  push:\n    branches:\n      - main\n", self.workflow)
        self.assertNotIn("- 'codex/**'", self.workflow)
        self.assertNotIn('- "codex/**"', self.workflow)


if __name__ == "__main__":
    unittest.main()
