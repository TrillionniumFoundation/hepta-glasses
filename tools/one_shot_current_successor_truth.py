#!/usr/bin/env python3
"""One-shot current-successor truth migration for PR #125.

The controller updates only the closed current-truth surface and its regression
checks. It writes no Git refs and creates no authority evidence.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
TARGET_FILES = (
    "README.md",
    "docs/CURRENT_STATE.md",
    "docs/PROJECT_STATE.json",
    "docs/development/2026-09-09_FULL_GAP_CLOSURE_PLAN.md",
    "docs/operations/FULL_GAP_CLOSURE_CONTROL_BOARD.md",
    "services/qualification/documentation_truth_core.py",
    "services/qualification/test_documentation_truth.py",
    "services/qualification/test_full_gap_closure_controls.py",
)

ACTIVE_PR = 125
ACTIVE_BRANCH = "codex/hepta-identity-migration-20260910"
ACTIVE_BASE_BRANCH = "codex/hepta-main-convergence-20260909-v2"
CANONICAL_MODULE_REGISTRY = "docs/modules/modules.json"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, observed {count}")
    return text.replace(old, new, 1)


def regex_once(text: str, pattern: str, replacement: str, label: str) -> str:
    result, count = re.subn(pattern, replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise SystemExit(f"{label}: expected one regex match, observed {count}")
    return result


def strict_object(path: Path) -> dict[str, Any]:
    def unique(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise SystemExit(f"duplicate JSON key in {path}: {key}")
            result[key] = value
        return result

    value = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=unique,
        parse_constant=lambda value: (_ for _ in ()).throw(
            SystemExit(f"non-finite JSON value in {path}: {value}")
        ),
    )
    if not isinstance(value, dict):
        raise SystemExit(f"{path} must contain an object")
    return value


def update_readme() -> None:
    path = ROOT / "README.md"
    text = path.read_text(encoding="utf-8")
    replacement = f"""The live head and Git tree of open PR #{ACTIVE_PR} identify the active successor source object. PR #{ACTIVE_PR} targets `{ACTIVE_BASE_BRANCH}` from `{ACTIVE_BRANCH}`. The live GitHub pull-request and commit readback—not a copied SHA in prose—determines the current source identity. The active successor remains `source_implemented`, not `ci_qualified`, `released`, or production-authorized, until one unchanged final head completes all seven jobs, yields a freshly inspected source Artifact, and receives an eligible non-author/non-latest-pusher approval.

The prior PR #114 object at commit `317ee1141ceac6df7d711aeaaca27b22d735e48d`, tree `51e673238d30b81ef8eb64b93eef14fc7bf850cb`, completed all seven jobs and produced source artifact `10098668276` with ZIP SHA-256 `6eac5358c5b0f1555043ac99250e583d5baeb7a89a2133365d72ad5bead7037c`. It is historical predecessor evidence only: it received artifact-integrity comments but no eligible `APPROVED` review, and neither its CI nor its Artifact attests PR #{ACTIVE_PR} or any later head.

"""
    text = regex_once(
        text,
        r"The live head and Git tree of open PR #114 identify the active successor source object\..*?must generate fresh CI, artifact and review evidence\.\n\n(?=The last independently qualified historical baseline remains PR #101)",
        replacement,
        "README active-successor block",
    )
    path.write_text(text, encoding="utf-8")


def update_current_state() -> None:
    path = ROOT / "docs/CURRENT_STATE.md"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "Last updated: 2026-09-09  ",
        "Last updated: 2026-09-10  ",
        "CURRENT_STATE date",
    )
    replacement = f"""The live head and Git tree of open PR #{ACTIVE_PR} identify the active successor source object. PR #{ACTIVE_PR} targets `{ACTIVE_BASE_BRANCH}` from `{ACTIVE_BRANCH}`. The live GitHub pull-request and commit readback, rather than a copied SHA in prose, determines the current source identity. Until one unchanged final head completes seven-job CI, fresh Artifact inspection and an eligible exact-head approval, the successor remains `source_implemented` and unqualified for product release.

The prior PR #114 object at commit `317ee1141ceac6df7d711aeaaca27b22d735e48d`, tree `51e673238d30b81ef8eb64b93eef14fc7bf850cb`, completed the seven canonical jobs and produced artifact `10098668276`, ZIP SHA-256 `6eac5358c5b0f1555043ac99250e583d5baeb7a89a2133365d72ad5bead7037c`. It is historical predecessor evidence only. It received bounded artifact-integrity comments but no eligible approval, and no result transfers to PR #{ACTIVE_PR} or a later source head.

"""
    text = regex_once(
        text,
        r"The live head and Git tree of open PR #114 identify the active successor source object\..*?no result transfers to the successor\.\n\n(?=`main` remains the older protected baseline)",
        replacement,
        "CURRENT_STATE active-successor block",
    )
    path.write_text(text, encoding="utf-8")


def update_project_state() -> None:
    path = ROOT / "docs/PROJECT_STATE.json"
    project = strict_object(path)
    if project.get("schema_version") != 5:
        raise SystemExit("PROJECT_STATE predecessor schema is not v5")
    gate = project.get("repository_actionable_gate")
    authority = project.get("source_authority")
    if not isinstance(gate, dict) or not isinstance(authority, dict):
        raise SystemExit("PROJECT_STATE truth objects are missing")
    if gate.get("module_registry") != "docs/MODULE_COVERAGE.json":
        raise SystemExit("PROJECT_STATE predecessor module registry drifted")
    expected_authority = {
        "branch": ACTIVE_BASE_BRANCH,
        "identity_rule": "live_pr_head_and_tree",
        "pull_request": 114,
        "repository": "TrillionniumFoundation/hepta-glasses",
        "required_artifact": "hepta-source-evidence-<exact-head-sha>",
        "self_attested_sha_is_authoritative": False,
        "historical_artifact_does_not_attest_later_push": True,
        "main_remains_older_until_protected_adoption": True,
    }
    if authority != expected_authority:
        raise SystemExit("PROJECT_STATE predecessor source authority drifted")

    project["schema_version"] = 6
    gate["module_registry"] = CANONICAL_MODULE_REGISTRY
    project["source_authority"] = {
        "base_branch": ACTIVE_BASE_BRANCH,
        "branch": ACTIVE_BRANCH,
        "identity_rule": "live_pull_request_head_and_tree",
        "pull_request": ACTIVE_PR,
        "repository": "TrillionniumFoundation/hepta-glasses",
        "required_artifact": "hepta-source-evidence-<exact-head-sha>",
        "self_attested_sha_is_authoritative": False,
        "historical_artifact_does_not_attest_later_push": True,
        "main_remains_older_until_protected_adoption": True,
    }
    path.write_text(
        json.dumps(project, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def update_plan() -> None:
    path = ROOT / "docs/development/2026-09-09_FULL_GAP_CLOSURE_PLAN.md"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "Status: active execution refinement for PR #114 and the G11 terminal-closure program.  ",
        f"Status: active execution refinement for PR #{ACTIVE_PR} and the G11 terminal-closure program.  ",
        "closure-plan status",
    )
    replacement = f"""The active source subject is the live head and Git tree of open PR #{ACTIVE_PR}, whose head branch is `{ACTIVE_BRANCH}` and whose base branch is `{ACTIVE_BASE_BRANCH}`. A SHA copied into this plan is never current-source authority. The final unchanged head must obtain its own seven-job execution, source Artifact inspection and eligible independent approval.

PR #114 at commit `317ee1141ceac6df7d711aeaaca27b22d735e48d`, tree `51e673238d30b81ef8eb64b93eef14fc7bf850cb`, is retained only as a historical predecessor observation. Its CI, Artifact, review state and prospective merge do not transfer to PR #{ACTIVE_PR}.

`main` remains the older baseline until canonical protection is applied and independently read back, followed by ordinary protected adoption.
"""
    text = regex_once(
        text,
        r"The closure campaign starts from the source candidate formerly observed at PR #114 head.*?`main` remains the older baseline until canonical protection is applied and independently read back, followed by ordinary protected adoption\.\n",
        replacement,
        "closure-plan starting state",
    )
    text = replace_once(
        text,
        "- correct `README.md`, `docs/CURRENT_STATE.md`, and `docs/PROJECT_STATE.json` so PR #114 is the live successor while PR #101 remains only the last independently qualified historical baseline;",
        f"- keep `README.md`, `docs/CURRENT_STATE.md`, and `docs/PROJECT_STATE.json` bound to the live head/tree of PR #{ACTIVE_PR}, while PR #101 remains only the last independently qualified historical baseline;",
        "closure-plan immediate truth action",
    )
    path.write_text(text, encoding="utf-8")


def update_control_board() -> None:
    path = ROOT / "docs/operations/FULL_GAP_CLOSURE_CONTROL_BOARD.md"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "Status date: 2026-09-09  ",
        "Status date: 2026-09-10  ",
        "control-board date",
    )
    anchor = (
        "This board is a coordination surface. It never replaces GitHub API state, "
        "provider records, physical measurements, vendor authorization, signatures, "
        "independent review, store decisions, or the canonical evidence validators.\n"
    )
    addition = (
        anchor
        + f"\nActive source subject: the live head and Git tree of open PR #{ACTIVE_PR} "
        + f"(`{ACTIVE_BRANCH}` into `{ACTIVE_BASE_BRANCH}`). The board deliberately "
        + "stores no copied current-head SHA; every execution re-reads GitHub before "
        + "binding evidence or reviewer eligibility.\n"
    )
    text = replace_once(text, anchor, addition, "control-board active subject")
    path.write_text(text, encoding="utf-8")


def update_validator() -> None:
    path = ROOT / "services/qualification/documentation_truth_core.py"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        'EXPECTED_REPOSITORY = "TrillionniumFoundation/hepta-glasses"\n',
        'EXPECTED_REPOSITORY = "TrillionniumFoundation/hepta-glasses"\n'
        'EXPECTED_PROJECT_STATE_SCHEMA = 6\n'
        f'EXPECTED_SUCCESSOR_PULL_REQUEST = {ACTIVE_PR}\n'
        f'EXPECTED_SUCCESSOR_BRANCH = "{ACTIVE_BRANCH}"\n'
        f'EXPECTED_SUCCESSOR_BASE_BRANCH = "{ACTIVE_BASE_BRANCH}"\n'
        'EXPECTED_SUCCESSOR_IDENTITY_RULE = "live_pull_request_head_and_tree"\n'
        f'EXPECTED_MODULE_REGISTRY = "{CANONICAL_MODULE_REGISTRY}"\n',
        "documentation truth successor constants",
    )
    text = replace_once(
        text,
        'SOURCE_AUTHORITY_KEYS = {\n    "branch",\n',
        'SOURCE_AUTHORITY_KEYS = {\n    "base_branch",\n    "branch",\n',
        "source authority base branch key",
    )
    text = replace_once(
        text,
        '    "final unchanged head still requires a fresh complete seven-lane result",\n)',
        '    "final unchanged head still requires a fresh complete seven-lane result",\n'
        '    "The live head and Git tree of open PR #114 identify the active successor source object",\n'
        '    "so PR #114 is the live successor",\n'
        ')',
        "stale current-successor phrases",
    )
    text = replace_once(
        text,
        '    if project.get("schema_version") != 5:\n        fail("PROJECT_STATE schema_version must be 5")\n',
        '    if project.get("schema_version") != EXPECTED_PROJECT_STATE_SCHEMA:\n'
        '        fail(\n'
        '            "PROJECT_STATE schema_version must be "\n'
        '            f"{EXPECTED_PROJECT_STATE_SCHEMA}"\n'
        '        )\n',
        "PROJECT_STATE schema validation",
    )
    text = replace_once(
        text,
        '    if gate.get("documentation_truth_validator") != (\n'
        '        "services/qualification/documentation_truth.py"\n'
        '    ):\n'
        '        fail("PROJECT_STATE does not register documentation truth")\n',
        '    if gate.get("documentation_truth_validator") != (\n'
        '        "services/qualification/documentation_truth.py"\n'
        '    ):\n'
        '        fail("PROJECT_STATE does not register documentation truth")\n'
        '    if gate.get("module_registry") != EXPECTED_MODULE_REGISTRY:\n'
        '        fail("PROJECT_STATE does not point to the canonical module registry")\n',
        "canonical module registry validation",
    )
    text = replace_once(
        text,
        '    if source_authority.get("repository") != EXPECTED_REPOSITORY:\n'
        '        fail("source authority repository drifted")\n',
        '    if source_authority.get("repository") != EXPECTED_REPOSITORY:\n'
        '        fail("source authority repository drifted")\n'
        '    if source_authority.get("pull_request") != EXPECTED_SUCCESSOR_PULL_REQUEST:\n'
        '        fail("source authority pull request drifted")\n'
        '    if source_authority.get("branch") != EXPECTED_SUCCESSOR_BRANCH:\n'
        '        fail("source authority head branch drifted")\n'
        '    if source_authority.get("base_branch") != EXPECTED_SUCCESSOR_BASE_BRANCH:\n'
        '        fail("source authority base branch drifted")\n'
        '    if source_authority.get("identity_rule") != EXPECTED_SUCCESSOR_IDENTITY_RULE:\n'
        '        fail("source authority identity rule drifted")\n'
        '    if source_authority.get("required_artifact") != (\n'
        '        "hepta-source-evidence-<exact-head-sha>"\n'
        '    ):\n'
        '        fail("source authority Artifact pattern drifted")\n',
        "source authority exact pointer validation",
    )
    text = replace_once(
        text,
        '        require_phrase(text, PINNED_BASELINE["artifact_zip_sha256"], document=relative)\n',
        '        require_phrase(text, PINNED_BASELINE["artifact_zip_sha256"], document=relative)\n'
        '        require_phrase(\n'
        '            text,\n'
        '            f"open PR #{EXPECTED_SUCCESSOR_PULL_REQUEST}",\n'
        '            document=relative,\n'
        '        )\n'
        '        require_phrase(text, EXPECTED_SUCCESSOR_BRANCH, document=relative)\n'
        '        require_phrase(text, EXPECTED_SUCCESSOR_BASE_BRANCH, document=relative)\n',
        "current successor prose binding",
    )
    text = replace_once(
        text,
        '        "required_jobs": len(EXPECTED_REQUIRED_JOBS),\n    }\n',
        '        "required_jobs": len(EXPECTED_REQUIRED_JOBS),\n'
        '        "successor_pull_request": EXPECTED_SUCCESSOR_PULL_REQUEST,\n'
        '        "successor_branch": EXPECTED_SUCCESSOR_BRANCH,\n'
        '        "successor_base_branch": EXPECTED_SUCCESSOR_BASE_BRANCH,\n'
        '        "module_registry": EXPECTED_MODULE_REGISTRY,\n'
        '    }\n',
        "documentation truth result fields",
    )

    live_block = '''    successor_pull = _stable_api_object(
        f"/repos/{EXPECTED_REPOSITORY}/pulls/{EXPECTED_SUCCESSOR_PULL_REQUEST}",
        token=auth,
    )
    if successor_pull.get("number") != EXPECTED_SUCCESSOR_PULL_REQUEST:
        fail("current successor pull-request identity drifted")
    if successor_pull.get("state") != "open" or successor_pull.get("merged_at") is not None:
        fail("current successor pull request is not open and unmerged")
    if _require_path(successor_pull, ("head", "ref"), label="successor pull") != EXPECTED_SUCCESSOR_BRANCH:
        fail("current successor head branch drifted")
    if _require_path(successor_pull, ("base", "ref"), label="successor pull") != EXPECTED_SUCCESSOR_BASE_BRANCH:
        fail("current successor base branch drifted")
    if _require_path(successor_pull, ("head", "repo", "full_name"), label="successor pull") != EXPECTED_REPOSITORY:
        fail("current successor head repository drifted")
    successor_head = require_sha(
        _require_path(successor_pull, ("head", "sha"), label="successor pull"),
        label="current successor head",
        width=40,
    )
    expected_execution_head = os.environ.get("SOURCE_HEAD_SHA")
    if expected_execution_head and successor_head != expected_execution_head:
        fail("current successor live head differs from the executing source head")
    successor_commit = _stable_api_object(
        f"/repos/{EXPECTED_REPOSITORY}/commits/{successor_head}",
        token=auth,
    )
    if successor_commit.get("sha") != successor_head:
        fail("current successor commit identity drifted")
    successor_tree = require_sha(
        _require_path(successor_commit, ("commit", "tree", "sha"), label="successor commit"),
        label="current successor tree",
        width=40,
    )

'''
    text = replace_once(
        text,
        '    owner_repo = EXPECTED_REPOSITORY\n',
        live_block + '    owner_repo = EXPECTED_REPOSITORY\n',
        "live current-successor API verification",
    )
    text = replace_once(
        text,
        '        "stable_double_reads": True,\n    }\n\n\ndef main(',
        '        "stable_double_reads": True,\n'
        '        "current_successor": {\n'
        '            "pull_request": EXPECTED_SUCCESSOR_PULL_REQUEST,\n'
        '            "branch": EXPECTED_SUCCESSOR_BRANCH,\n'
        '            "base_branch": EXPECTED_SUCCESSOR_BASE_BRANCH,\n'
        '            "head": successor_head,\n'
        '            "tree": successor_tree,\n'
        '        },\n'
        '    }\n\n\ndef main(',
        "live successor verification result",
    )
    path.write_text(text, encoding="utf-8")


def update_documentation_tests() -> None:
    path = ROOT / "services/qualification/test_documentation_truth.py"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '        self.assertEqual(result["last_qualified_commit"], PINNED_BASELINE["commit"])\n',
        '        self.assertEqual(result["last_qualified_commit"], PINNED_BASELINE["commit"])\n'
        f'        self.assertEqual(result["successor_pull_request"], {ACTIVE_PR})\n'
        f'        self.assertEqual(result["successor_branch"], "{ACTIVE_BRANCH}")\n'
        f'        self.assertEqual(result["successor_base_branch"], "{ACTIVE_BASE_BRANCH}")\n'
        f'        self.assertEqual(result["module_registry"], "{CANONICAL_MODULE_REGISTRY}")\n',
        "documentation truth positive successor assertions",
    )
    anchor = '''    def test_required_check_drift_is_rejected(self) -> None:
        project = self.project()
        project["repository_actionable_gate"]["required_checks"].pop()
        self.save_project(project)
        with self.assertRaisesRegex(DocumentationTruthError, "required check set drifted"):
            validate(self.root)

'''
    addition = anchor + f'''    def test_current_successor_pointer_drift_is_rejected(self) -> None:
        project = self.project()
        project["source_authority"]["pull_request"] = 114
        self.save_project(project)
        with self.assertRaisesRegex(DocumentationTruthError, "pull request drifted"):
            validate(self.root)

    def test_current_successor_branch_drift_is_rejected(self) -> None:
        project = self.project()
        project["source_authority"]["branch"] = "wrong-branch"
        self.save_project(project)
        with self.assertRaisesRegex(DocumentationTruthError, "head branch drifted"):
            validate(self.root)

    def test_canonical_module_registry_pointer_drift_is_rejected(self) -> None:
        project = self.project()
        project["repository_actionable_gate"]["module_registry"] = "docs/MODULE_COVERAGE.json"
        self.save_project(project)
        with self.assertRaisesRegex(DocumentationTruthError, "canonical module registry"):
            validate(self.root)

'''
    text = replace_once(
        text,
        anchor,
        addition,
        "documentation truth successor negative tests",
    )
    path.write_text(text, encoding="utf-8")


def update_closure_tests() -> None:
    path = ROOT / "services/qualification/test_full_gap_closure_controls.py"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '            "The last independently qualified baseline is Draft PR #101",\n',
        '            "The last independently qualified baseline is Draft PR #101",\n'
        '            "The live head and Git tree of open PR #114 identify the active successor source object",\n',
        "closure test stale successor phrase",
    )
    text = replace_once(
        text,
        '            self.assertIn("open PR #114", text)\n',
        f'            self.assertIn("open PR #{ACTIVE_PR}", text)\n'
        f'            self.assertIn("{ACTIVE_BRANCH}", text)\n'
        f'            self.assertIn("{ACTIVE_BASE_BRANCH}", text)\n',
        "closure test live successor prose",
    )
    text = replace_once(
        text,
        '        self.assertEqual(authority["pull_request"], 114)\n'
        '        self.assertEqual(\n'
        '            authority["branch"],\n'
        '            "codex/hepta-main-convergence-20260909-v2",\n'
        '        )\n',
        f'        self.assertEqual(project["schema_version"], 6)\n'
        f'        self.assertEqual(authority["pull_request"], {ACTIVE_PR})\n'
        f'        self.assertEqual(authority["branch"], "{ACTIVE_BRANCH}")\n'
        f'        self.assertEqual(authority["base_branch"], "{ACTIVE_BASE_BRANCH}")\n'
        '        self.assertEqual(\n'
        '            authority["identity_rule"],\n'
        '            "live_pull_request_head_and_tree",\n'
        '        )\n'
        f'        self.assertEqual(\n'
        f'            project["repository_actionable_gate"]["module_registry"],\n'
        f'            "{CANONICAL_MODULE_REGISTRY}",\n'
        f'        )\n',
        "closure test machine successor pointer",
    )
    text = replace_once(
        text,
        '        self.assertIn("coordination surface", board)\n',
        '        self.assertIn("coordination surface", board)\n'
        f'        self.assertIn("open PR #{ACTIVE_PR}", board)\n'
        f'        self.assertIn("{ACTIVE_BRANCH}", board)\n',
        "closure test board active subject",
    )
    path.write_text(text, encoding="utf-8")


def assert_no_stale_active_truth() -> None:
    checks = {
        "README.md": (
            "The live head and Git tree of open PR #114 identify the active successor source object",
        ),
        "docs/CURRENT_STATE.md": (
            "The live head and Git tree of open PR #114 identify the active successor source object",
        ),
        "docs/development/2026-09-09_FULL_GAP_CLOSURE_PLAN.md": (
            "so PR #114 is the live successor",
            "active execution refinement for PR #114",
        ),
        "services/qualification/test_full_gap_closure_controls.py": (
            'self.assertIn("open PR #114", text)',
            'authority["pull_request"], 114',
        ),
    }
    for relative, stale_values in checks.items():
        text = (ROOT / relative).read_text(encoding="utf-8")
        for stale in stale_values:
            if stale in text:
                raise SystemExit(f"stale active-successor truth remains in {relative}: {stale}")


def main() -> int:
    update_readme()
    update_current_state()
    update_project_state()
    update_plan()
    update_control_board()
    update_validator()
    update_documentation_tests()
    update_closure_tests()
    assert_no_stale_active_truth()
    changed = tuple(
        sorted(
            relative
            for relative in TARGET_FILES
            if (ROOT / relative).is_file()
        )
    )
    if changed != tuple(sorted(TARGET_FILES)):
        raise SystemExit("target file inventory drifted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
