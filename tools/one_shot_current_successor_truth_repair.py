#!/usr/bin/env python3
"""Repair the PR #125 live-readback fixtures and canonical job parser.

This script composes the bounded current-successor migration and adds only the
two test updates exposed by the first complete validation run.
"""

from __future__ import annotations

from pathlib import Path

from tools import one_shot_current_successor_truth as base

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, observed {count}")
    return text.replace(old, new, 1)


def update_live_fixture() -> None:
    path = ROOT / "services/qualification/test_documentation_truth_live.py"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '        review_id = pin["code_owner_review_id"]\n        self.paths = {\n',
        '        review_id = pin["code_owner_review_id"]\n'
        '        self.successor_head = "1" * 40\n'
        '        self.successor_tree = "2" * 40\n'
        '        self.paths = {\n'
        '            "successor_pull": (\n'
        '                f"/repos/{truth.EXPECTED_REPOSITORY}/pulls/"\n'
        '                f"{truth.EXPECTED_SUCCESSOR_PULL_REQUEST}"\n'
        '            ),\n'
        '            "successor_commit": (\n'
        '                f"/repos/{truth.EXPECTED_REPOSITORY}/commits/"\n'
        '                f"{self.successor_head}"\n'
        '            ),\n',
        "live fixture successor paths",
    )
    text = replace_once(
        text,
        '        self.payloads = {\n            self.paths["commit"]: {\n',
        '        self.payloads = {\n'
        '            self.paths["successor_pull"]: {\n'
        '                "number": truth.EXPECTED_SUCCESSOR_PULL_REQUEST,\n'
        '                "state": "open",\n'
        '                "merged_at": None,\n'
        '                "head": {\n'
        '                    "ref": truth.EXPECTED_SUCCESSOR_BRANCH,\n'
        '                    "sha": self.successor_head,\n'
        '                    "repo": {"full_name": truth.EXPECTED_REPOSITORY},\n'
        '                },\n'
        '                "base": {\n'
        '                    "ref": truth.EXPECTED_SUCCESSOR_BASE_BRANCH,\n'
        '                },\n'
        '            },\n'
        '            self.paths["successor_commit"]: {\n'
        '                "sha": self.successor_head,\n'
        '                "commit": {"tree": {"sha": self.successor_tree}},\n'
        '            },\n'
        '            self.paths["commit"]: {\n',
        "live fixture successor payloads",
    )
    text = replace_once(
        text,
        '                {"GITHUB_REPOSITORY": truth.EXPECTED_REPOSITORY},\n',
        '                {\n'
        '                    "GITHUB_REPOSITORY": truth.EXPECTED_REPOSITORY,\n'
        '                    "SOURCE_HEAD_SHA": self.successor_head,\n'
        '                },\n',
        "live fixture executing source head",
    )
    text = replace_once(
        text,
        '        self.assertTrue(result["stable_double_reads"])\n\n'
        '    def test_commit_tree_substitution_is_rejected(self) -> None:\n',
        '        self.assertTrue(result["stable_double_reads"])\n'
        '        self.assertEqual(\n'
        '            result["current_successor"]["head"],\n'
        '            self.successor_head,\n'
        '        )\n'
        '        self.assertEqual(\n'
        '            result["current_successor"]["tree"],\n'
        '            self.successor_tree,\n'
        '        )\n\n'
        '    def test_successor_branch_substitution_is_rejected(self) -> None:\n'
        '        self.payloads[self.paths["successor_pull"]]["head"]["ref"] = (\n'
        '            "wrong-successor-branch"\n'
        '        )\n'
        '        with self.assertRaisesRegex(\n'
        '            truth.DocumentationTruthError, "head branch drifted"\n'
        '        ):\n'
        '            self.verify()\n\n'
        '    def test_successor_tree_substitution_is_rejected(self) -> None:\n'
        '        self.payloads[self.paths["successor_commit"]]["commit"]["tree"][\n'
        '            "sha"\n'
        '        ] = "0" * 40\n'
        '        result = self.verify()\n'
        '        self.assertEqual(result["current_successor"]["tree"], "0" * 40)\n\n'
        '    def test_commit_tree_substitution_is_rejected(self) -> None:\n',
        "live fixture successor assertions",
    )
    path.write_text(text, encoding="utf-8")


def update_job_matrix_parser() -> None:
    path = ROOT / "services/qualification/test_server_provider_boundary.py"
    text = path.read_text(encoding="utf-8")
    old = '''    def test_canonical_job_matrix_is_unchanged(self):
        workflow = (ROOT / ".github/workflows/ci.yml").read_text()
        self.assertEqual(set(__import__("re").findall(r"^  ([a-z][a-z-]+):$", workflow, __import__("re").M))
                         - {"workflow-dispatch", "pull-request", "push"}, repository.EXPECTED_CHECKS)
        with patch.object(repository, "ROOT", ROOT):
            repository.validate_exact_head_workflow()
'''
    new = '''    def test_canonical_job_matrix_is_unchanged(self):
        workflow = (ROOT / ".github/workflows/ci.yml").read_text()
        self.assertEqual(workflow.count("\\njobs:\\n"), 1)
        jobs = workflow.split("\\njobs:\\n", 1)[1]
        self.assertEqual(
            set(
                __import__("re").findall(
                    r"^  ([a-z][a-z-]+):$",
                    jobs,
                    __import__("re").M,
                )
            ),
            repository.EXPECTED_CHECKS,
        )
        with patch.object(repository, "ROOT", ROOT):
            repository.validate_exact_head_workflow()
'''
    text = replace_once(text, old, new, "canonical job matrix parser")
    path.write_text(text, encoding="utf-8")


def main() -> int:
    base.main()
    update_live_fixture()
    update_job_matrix_parser()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
