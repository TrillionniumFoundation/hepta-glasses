from __future__ import annotations

import base64
import copy
import os
import unittest
from unittest import mock

from services.qualification import documentation_truth as truth


class LiveQualificationBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        pin = truth.PINNED_BASELINE
        commit = pin["commit"]
        tree = pin["tree"]
        base = pin["base_commit"]
        run_id = pin["workflow_run_id"]
        artifact_id = pin["artifact_id"]
        review_id = pin["code_owner_review_id"]
        self.successor_head = "1" * 40
        self.successor_tree = "2" * 40
        self.paths = {
            "successor_pull": (
                f"/repos/{truth.EXPECTED_REPOSITORY}/pulls/"
                f"{truth.EXPECTED_SUCCESSOR_PULL_REQUEST}"
            ),
            "successor_commit": (
                f"/repos/{truth.EXPECTED_REPOSITORY}/commits/"
                f"{self.successor_head}"
            ),
            "commit": f"/repos/{truth.EXPECTED_REPOSITORY}/commits/{commit}",
            "pull": f"/repos/{truth.EXPECTED_REPOSITORY}/pulls/{pin['pull_request']}",
            "run": f"/repos/{truth.EXPECTED_REPOSITORY}/actions/runs/{run_id}",
            "jobs": (
                f"/repos/{truth.EXPECTED_REPOSITORY}/actions/runs/{run_id}"
                "/jobs?filter=latest&per_page=100"
            ),
            "artifacts": (
                f"/repos/{truth.EXPECTED_REPOSITORY}/actions/runs/{run_id}"
                "/artifacts?per_page=100"
            ),
            "review": (
                f"/repos/{truth.EXPECTED_REPOSITORY}/pulls/{pin['pull_request']}"
                f"/reviews/{review_id}"
            ),
            "codeowners": (
                f"/repos/{truth.EXPECTED_REPOSITORY}/contents/.github/CODEOWNERS"
                f"?ref={base}"
            ),
        }
        jobs = []
        for name in truth.EXPECTED_REQUIRED_JOBS:
            jobs.append(
                {
                    "name": name,
                    "run_id": run_id,
                    "head_sha": commit,
                    "status": "completed",
                    "conclusion": "success",
                    "steps": [
                        {
                            "name": "Set up job",
                            "number": 1,
                            "status": "completed",
                            "conclusion": "success",
                        },
                        {
                            "name": "Checkout",
                            "number": 2,
                            "status": "completed",
                            "conclusion": "success",
                        },
                        {
                            "name": "Verify exact source identity",
                            "number": 3,
                            "status": "completed",
                            "conclusion": "success",
                        },
                        {
                            "name": f"Run {name}",
                            "number": 4,
                            "status": "completed",
                            "conclusion": "success",
                        },
                    ],
                }
            )
        self.payloads = {
            self.paths["successor_pull"]: {
                "number": truth.EXPECTED_SUCCESSOR_PULL_REQUEST,
                "state": "open",
                "merged_at": None,
                "head": {
                    "ref": truth.EXPECTED_SUCCESSOR_BRANCH,
                    "sha": self.successor_head,
                    "repo": {"full_name": truth.EXPECTED_REPOSITORY},
                },
                "base": {
                    "ref": truth.EXPECTED_SUCCESSOR_BASE_BRANCH,
                },
            },
            self.paths["successor_commit"]: {
                "sha": self.successor_head,
                "commit": {"tree": {"sha": self.successor_tree}},
            },
            self.paths["commit"]: {
                "sha": commit,
                "commit": {"tree": {"sha": tree}},
                "author": {"login": pin["source_pusher"]},
            },
            self.paths["pull"]: {
                "number": pin["pull_request"],
                "head": {"sha": commit},
                "base": {"sha": base},
                "user": {"login": pin["pull_request_author"]},
            },
            self.paths["run"]: {
                "id": run_id,
                "workflow_id": pin["workflow_id"],
                "name": pin["workflow_name"],
                "run_number": pin["workflow_run_number"],
                "run_attempt": pin["workflow_run_attempt"],
                "event": pin["workflow_event"],
                "head_sha": commit,
                "status": "completed",
                "conclusion": "success",
                "head_commit": {"id": commit, "tree_id": tree},
                "pull_requests": [
                    {
                        "number": pin["pull_request"],
                        "head": {"sha": commit},
                        "base": {"sha": base},
                    }
                ],
                "updated_at": "2026-09-07T15:54:24Z",
            },
            self.paths["jobs"]: {
                "total_count": len(jobs),
                "jobs": jobs,
            },
            self.paths["artifacts"]: {
                "artifacts": [
                    {
                        "id": artifact_id,
                        "name": pin["artifact_name"],
                        "digest": f"sha256:{pin['artifact_zip_sha256']}",
                        "expired": False,
                        "workflow_run": {
                            "id": run_id,
                            "repository_id": pin["repository_id"],
                            "head_sha": commit,
                        },
                    }
                ]
            },
            self.paths["review"]: {
                "id": review_id,
                "state": pin["code_owner_review_state"],
                "commit_id": commit,
                "user": {"login": pin["code_owner_reviewer"]},
                "body": f"approved {commit} run {run_id} artifact {artifact_id}",
                "submitted_at": "2026-09-07T16:00:09Z",
            },
            self.paths["codeowners"]: {
                "encoding": "base64",
                "content": base64.b64encode(
                    b"* @ProfHepta @Tomasrgbsf\n"
                ).decode("ascii"),
            },
        }

    def api(self, path: str, *, token: str):
        self.assertEqual(token, "fixture-token")
        return copy.deepcopy(self.payloads[path])

    def verify(self):
        with (
            mock.patch.dict(
                os.environ,
                {
                    "GITHUB_REPOSITORY": truth.EXPECTED_REPOSITORY,
                    "SOURCE_HEAD_SHA": self.successor_head,
                },
                clear=False,
            ),
            mock.patch.object(
                truth, "_stable_api_object", side_effect=self.api
            ),
            mock.patch.object(
                truth, "_stable_artifact_zip", return_value=b"fixture-zip"
            ),
            mock.patch.object(
                truth,
                "_verify_artifact_zip",
                return_value=[f"member-{index}.json" for index in range(7)],
            ),
        ):
            return truth.verify_github_baseline("fixture-token")

    def test_complete_binding_is_accepted(self) -> None:
        result = self.verify()
        self.assertEqual(result["jobs"], 7)
        self.assertEqual(result["reviewer"], "Tomasrgbsf")
        self.assertTrue(result["stable_double_reads"])
        self.assertEqual(
            result["current_successor"]["head"],
            self.successor_head,
        )
        self.assertEqual(
            result["current_successor"]["tree"],
            self.successor_tree,
        )

    def test_successor_branch_substitution_is_rejected(self) -> None:
        self.payloads[self.paths["successor_pull"]]["head"]["ref"] = (
            "wrong-successor-branch"
        )
        with self.assertRaisesRegex(
            truth.DocumentationTruthError, "head branch drifted"
        ):
            self.verify()

    def test_successor_tree_malformed_sha_is_rejected(self) -> None:
        self.payloads[self.paths["successor_commit"]]["commit"]["tree"][
            "sha"
        ] = "not-a-sha"
        with self.assertRaisesRegex(
            truth.DocumentationTruthError, "current successor tree"
        ):
            self.verify()

    def test_commit_tree_substitution_is_rejected(self) -> None:
        self.payloads[self.paths["commit"]]["commit"]["tree"]["sha"] = "0" * 40
        with self.assertRaisesRegex(truth.DocumentationTruthError, "pinned tree"):
            self.verify()

    def test_pull_head_substitution_is_rejected(self) -> None:
        self.payloads[self.paths["pull"]]["head"]["sha"] = "0" * 40
        with self.assertRaisesRegex(truth.DocumentationTruthError, "head drifted"):
            self.verify()

    def test_run_head_substitution_is_rejected(self) -> None:
        self.payloads[self.paths["run"]]["head_sha"] = "0" * 40
        with self.assertRaisesRegex(truth.DocumentationTruthError, "head_sha"):
            self.verify()

    def test_missing_job_is_rejected(self) -> None:
        jobs = self.payloads[self.paths["jobs"]]["jobs"]
        jobs.pop()
        self.payloads[self.paths["jobs"]]["total_count"] = len(jobs)
        with self.assertRaisesRegex(truth.DocumentationTruthError, "exactly seven"):
            self.verify()

    def test_empty_job_is_rejected(self) -> None:
        self.payloads[self.paths["jobs"]]["jobs"][0]["steps"] = []
        with self.assertRaisesRegex(truth.DocumentationTruthError, "empty"):
            self.verify()

    def test_artifact_digest_substitution_is_rejected(self) -> None:
        artifact = self.payloads[self.paths["artifacts"]]["artifacts"][0]
        artifact["digest"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(truth.DocumentationTruthError, "server digest"):
            self.verify()

    def test_artifact_run_substitution_is_rejected(self) -> None:
        artifact = self.payloads[self.paths["artifacts"]]["artifacts"][0]
        artifact["workflow_run"]["id"] += 1
        with self.assertRaisesRegex(truth.DocumentationTruthError, "workflow binding"):
            self.verify()

    def test_review_commit_substitution_is_rejected(self) -> None:
        self.payloads[self.paths["review"]]["commit_id"] = "0" * 40
        with self.assertRaisesRegex(truth.DocumentationTruthError, "pinned commit"):
            self.verify()

    def test_review_decision_substitution_is_rejected(self) -> None:
        self.payloads[self.paths["review"]]["state"] = "CHANGES_REQUESTED"
        with self.assertRaisesRegex(truth.DocumentationTruthError, "APPROVED"):
            self.verify()

    def test_reviewer_source_actor_alias_is_rejected(self) -> None:
        self.payloads[self.paths["review"]]["user"]["login"] = "ProfHepta"
        truth.PINNED_BASELINE["code_owner_reviewer"] = "ProfHepta"
        try:
            with self.assertRaisesRegex(truth.DocumentationTruthError, "not independent"):
                self.verify()
        finally:
            truth.PINNED_BASELINE["code_owner_reviewer"] = "Tomasrgbsf"

    def test_missing_code_owner_route_is_rejected(self) -> None:
        self.payloads[self.paths["codeowners"]]["content"] = base64.b64encode(
            b"* @ProfHepta\n"
        ).decode("ascii")
        with self.assertRaisesRegex(truth.DocumentationTruthError, "not a base-branch"):
            self.verify()

    def test_review_before_terminal_run_is_rejected(self) -> None:
        self.payloads[self.paths["review"]]["submitted_at"] = (
            "2026-09-07T15:00:00Z"
        )
        with self.assertRaisesRegex(truth.DocumentationTruthError, "predates"):
            self.verify()


if __name__ == "__main__":
    unittest.main()
