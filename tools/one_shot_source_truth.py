#!/usr/bin/env python3
"""One-shot deterministic source-truth closure; removed by its executor."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def exact(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, observed {count}")
    return text.replace(old, new, 1)


def close_dependency_policy() -> None:
    policy_path = ROOT / "tools/native/dependency_update_policy.py"
    policy = policy_path.read_text(encoding="utf-8")
    marker = "\n\ndef verify_dependabot_official() -> dict[str, Any]:\n"
    local_contract = '''

def inspect_dependabot_contract() -> dict[str, Any]:
    """Validate committed update policy without external I/O."""
    contract = load_contract()
    configured = _configured_dependabot_values()
    expected = contract["configured_ecosystems"]
    if configured != expected:
        raise DependencyPolicyError(
            f"Dependabot ecosystems {configured} differ from contract {expected}"
        )
    unsupported = contract["unsupported_repository_managers"]
    if unsupported != ["cocoapods"]:
        raise DependencyPolicyError(
            "unsupported repository manager contract drifted"
        )
    if set(configured) & set(unsupported):
        raise DependencyPolicyError(
            "configured ecosystems overlap unsupported managers"
        )
    if not PODFILE.is_file() or not LOCKFILE.is_file():
        raise DependencyPolicyError("the declared CocoaPods graph is absent")
    if "cocoapods" in configured or "swift" in configured:
        raise DependencyPolicyError(
            "another ecosystem cannot substitute for the CocoaPods graph"
        )
    if (ROOT / "Package.swift").exists():
        raise DependencyPolicyError(
            "Package.swift appeared without a reviewed ecosystem change"
        )
    source = contract["official_source"]
    return {
        "schema_version": 1,
        "mode": "deterministic-committed-contract",
        "configured_ecosystems": configured,
        "unsupported_repository_managers": unsupported,
        "pinned_official_repository": source["repository"],
        "pinned_official_commit": source["commit"],
        "pinned_official_path": source["path"],
        "live_freshness_revalidation_required": True,
        "network_used": False,
        "passed": True,
    }
'''
    policy = exact(
        policy,
        marker,
        local_contract + marker,
        "insert deterministic Dependabot contract",
    )
    policy = exact(
        policy,
        '''    mode.add_argument(
        "--verify-dependabot-official",
        action="store_true",
        help=(
            "read the pinned github/docs table and reject unsupported "
            "YAML values"
        ),
    )
''',
        '''    mode.add_argument(
        "--verify-dependabot-official",
        action="store_true",
        help=(
            "read the pinned github/docs table and reject unsupported "
            "YAML values"
        ),
    )
    mode.add_argument(
        "--check-dependabot-contract",
        action="store_true",
        help="validate the committed dependency-update contract without network I/O",
    )
''',
        "add deterministic Dependabot CLI mode",
    )
    policy = exact(
        policy,
        '''        if args.verify_dependabot_official:
            result = verify_dependabot_official()
        elif args.emit_cocoapods_update_contract:
''',
        '''        if args.verify_dependabot_official:
            result = verify_dependabot_official()
        elif args.check_dependabot_contract:
            result = inspect_dependabot_contract()
        elif args.emit_cocoapods_update_contract:
''',
        "route deterministic Dependabot CLI mode",
    )
    policy_path.write_text(policy, encoding="utf-8")

    ci_path = ROOT / ".github/workflows/ci.yml"
    ci = ci_path.read_text(encoding="utf-8")
    ci = exact(
        ci,
        '''on:
  workflow_dispatch:
  pull_request:
  push:
''',
        '''on:
  workflow_dispatch:
  schedule:
    - cron: '17 3 * * 1'
  pull_request:
  push:
''',
        "add scheduled dependency freshness observation",
    )
    ci = exact(
        ci,
        '''      - name: Verify Dependabot values against immutable GitHub docs
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: python3 tools/native/dependency_update_policy.py --verify-dependabot-official
''',
        '''      - name: Verify committed Dependabot contract without network
        run: python3 tools/native/dependency_update_policy.py --check-dependabot-contract
      - name: Refresh Dependabot values against immutable GitHub docs
        if: github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: python3 tools/native/dependency_update_policy.py --verify-dependabot-official
''',
        "split deterministic and live dependency checks",
    )
    ci_path.write_text(ci, encoding="utf-8")

    encoded = ci.encode("utf-8")
    blob = hashlib.sha1(
        f"blob {len(encoded)}\0".encode("ascii") + encoded
    ).hexdigest()
    policy = policy_path.read_text(encoding="utf-8")
    policy, count = re.subn(
        r'(_APPROVED_WORKFLOW_GIT_BLOB_SHA1 = \(\n    ")[0-9a-f]{40}("\n\))',
        rf"\g<1>{blob}\g<2>",
        policy,
        count=1,
    )
    if count != 1:
        raise SystemExit("failed to update canonical workflow object binding")
    policy_path.write_text(policy, encoding="utf-8")

    test_path = ROOT / "services/qualification/test_dependency_update_policy.py"
    test = test_path.read_text(encoding="utf-8")
    test = exact(
        test,
        "import unittest\n",
        "import unittest\nfrom unittest import mock\n",
        "dependency test mock import",
    )
    methods = '''

    def test_deterministic_dependabot_contract_uses_no_network(self) -> None:
        with mock.patch.object(
            policy,
            "_fetch_official_document",
            side_effect=AssertionError("network must not be used"),
        ):
            result = policy.inspect_dependabot_contract()
        self.assertTrue(result["passed"])
        self.assertFalse(result["network_used"])
        self.assertEqual(
            result["configured_ecosystems"],
            ["github-actions", "gradle", "pub"],
        )

    def test_deterministic_dependabot_contract_rejects_config_drift(self) -> None:
        with mock.patch.object(
            policy,
            "_configured_dependabot_values",
            return_value=["github-actions", "pub"],
        ):
            with self.assertRaisesRegex(
                policy.DependencyPolicyError,
                "differ from contract",
            ):
                policy.inspect_dependabot_contract()
'''
    test = exact(
        test,
        '\n\nif __name__ == "__main__":\n',
        methods + '\n\nif __name__ == "__main__":\n',
        "append deterministic dependency tests",
    )
    test_path.write_text(test, encoding="utf-8")


def close_module_semantics() -> None:
    validator_path = ROOT / "tools/validate_module_semantics.py"
    validator = validator_path.read_text(encoding="utf-8")
    validator = exact(
        validator,
        "requires eight engineering dimensions, verifies every source/document/test/\ncontract reference, and rejects compatibility-layer drift.",
        "binds eleven canonical semantic dimensions to eight compact generated\nhandoff sections, verifies every source/document/test/contract reference, and\nrejects compatibility-layer drift.",
        "module validator description",
    )
    semantic_constant = '''CANONICAL_SEMANTIC_HEADINGS = (
    "### 1.1 Purpose, responsibility and non-goals",
    "### 1.2 Component and source map",
    "### 1.3 Public interfaces and contracts",
    "### 1.4 State machine and invariants",
    "### 1.5 Concurrency and atomicity",
    "### 1.6 Failure, retry, reconciliation and recovery",
    "### 1.7 Configuration, compatibility, migration and rollback",
    "### 1.8 Operations, observability and SLOs",
    "### 1.9 Security, privacy and abuse cases",
    "### 1.10 Verification and acceptance",
    "### 1.11 Ownership and change protocol",
)
STANDARD = Path("docs/development/MODULE_DOCUMENTATION_COMPLETENESS_STANDARD.md")
'''
    validator = exact(
        validator,
        "MINIMUM_PAGE_CHARACTERS = 2_000\n",
        semantic_constant + "MINIMUM_PAGE_CHARACTERS = 2_000\n",
        "canonical eleven module dimensions",
    )
    validator = exact(
        validator,
        '''    root = root.resolve()
    registry = load_canonical(root)
''',
        '''    root = root.resolve()
    standard_path = root / STANDARD
    if standard_path.is_symlink() or not standard_path.is_file():
        fail("module documentation completeness standard is missing or linked")
    standard_text = standard_path.read_text(encoding="utf-8")
    positions = [
        standard_text.find(heading) for heading in CANONICAL_SEMANTIC_HEADINGS
    ]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        fail("canonical eleven module semantic dimensions drifted")
    registry = load_canonical(root)
''',
        "validate canonical semantic standard",
    )
    validator = exact(
        validator,
        '''        "semantic_dimensions": len(REQUIRED_HEADINGS),
    }
''',
        '''        "semantic_dimensions": len(CANONICAL_SEMANTIC_HEADINGS),
        "generated_handoff_sections": len(REQUIRED_HEADINGS),
    }
''',
        "report semantic and generated dimensions separately",
    )
    validator_path.write_text(validator, encoding="utf-8")

    test_path = ROOT / "services/qualification/test_module_semantic_docs.py"
    test = test_path.read_text(encoding="utf-8")
    test = exact(
        test,
        "from tools.validate_module_semantics import REQUIRED_HEADINGS, validate\n",
        "from tools.validate_module_semantics import (\n"
        "    CANONICAL_SEMANTIC_HEADINGS,\n"
        "    REQUIRED_HEADINGS,\n"
        "    validate,\n"
        ")\n",
        "module semantic test imports",
    )
    test = exact(
        test,
        '        self.assertEqual(result["semantic_dimensions"], 8)\n',
        '        self.assertEqual(result["semantic_dimensions"], 11)\n'
        '        self.assertEqual(result["generated_handoff_sections"], 8)\n',
        "module semantic result assertion",
    )
    test = exact(
        test,
        "    def test_generated_page_binds_all_eight_dimensions_and_module_data(self) -> None:\n",
        "    def test_generated_page_binds_all_compact_sections_and_module_data(self) -> None:\n",
        "module generated test name",
    )
    test = exact(
        test,
        '''        self.assertEqual(positions, sorted(positions))
        self.assertIn(module_digest(module), rendered)
''',
        '''        self.assertEqual(positions, sorted(positions))
        standard = (
            root / "docs/development/MODULE_DOCUMENTATION_COMPLETENESS_STANDARD.md"
        ).read_text(encoding="utf-8")
        semantic_positions = [
            standard.index(heading) for heading in CANONICAL_SEMANTIC_HEADINGS
        ]
        self.assertEqual(semantic_positions, sorted(semantic_positions))
        self.assertIn(module_digest(module), rendered)
''',
        "module eleven-dimension test binding",
    )
    test_path.write_text(test, encoding="utf-8")


def close_candidate_truth() -> None:
    readme_path = ROOT / "README.md"
    readme = readme_path.read_text(encoding="utf-8")
    readme = exact(
        readme,
        '''The live head and Git tree of open PR #114 identify the active successor source object. PR #114 targets `main` from `codex/hepta-main-convergence-20260909-v2`; it is out of Draft but still requires an eligible non-author/non-latest-pusher Code Owner `APPROVED` review, complete canonical `main` protection readback, and ordinary protected adoption. The active successor therefore remains `source_implemented`, not `ci_qualified`, `released`, or production-authorized.

The immediately preceding PR #114 object at commit `317ee1141ceac6df7d711aeaaca27b22d735e48d`, tree `51e673238d30b81ef8eb64b93eef14fc7bf850cb`, completed all seven jobs and produced source artifact `10098668276` with ZIP SHA-256 `6eac5358c5b0f1555043ac99250e583d5baeb7a89a2133365d72ad5bead7037c`. It received artifact-integrity comments but no eligible `APPROVED` review. Any later source commit—including the closure-control refinement described below—supersedes that exact-head evidence and must generate fresh CI, artifact and review evidence.
''',
        '''PR #114 remains the adoption root targeting `main`. The active stacked source review is PR #125 on `codex/hepta-identity-migration-20260910`; `docs/CURRENT_CANDIDATE.json` is the machine-readable pointer. The live GitHub API is authoritative for its head, tree, Draft state, checks, Artifact and reviews. No SHA, run, Artifact or review copied into Markdown qualifies a moving successor.

PR #125 remains `source_implemented` until one unchanged final head completes all seven canonical jobs, its exact-head Artifact is independently inspected, and an eligible non-author/non-latest-pusher Code Owner approves it. Historical PR #114 and #117 executions do not transfer to that final head. Protected `main` adoption and every E5–E7 fact remain separate gates.
''',
        "README live candidate truth",
    )
    readme = exact(
        readme,
        "- `docs/CURRENT_STATE.md` — current source, governance, platform, and external-authority truth.\n",
        "- `docs/CURRENT_CANDIDATE.json` — live-review pointer without a self-attested moving SHA.\n"
        "- `docs/CURRENT_STATE.md` — current source, governance, platform, and external-authority truth.\n",
        "README candidate pointer index",
    )
    readme_path.write_text(readme, encoding="utf-8")

    current_path = ROOT / "docs/CURRENT_STATE.md"
    current = current_path.read_text(encoding="utf-8")
    current = exact(
        current,
        "Last updated: 2026-09-09  \n",
        "Last updated: 2026-09-10  \n",
        "current state date",
    )
    current = exact(
        current,
        '''The live head and Git tree of open PR #114 identify the active successor source object. PR #114 targets `main` from `codex/hepta-main-convergence-20260909-v2`. It is out of Draft but has no eligible exact-head Code Owner `APPROVED` review, no complete Administration-capable `main` protection readback and no protected adoption. The current successor therefore remains `source_implemented` and unqualified for product release.

The immediately preceding PR #114 object at commit `317ee1141ceac6df7d711aeaaca27b22d735e48d`, tree `51e673238d30b81ef8eb64b93eef14fc7bf850cb`, completed the seven canonical jobs and produced artifact `10098668276`, ZIP SHA-256 `6eac5358c5b0f1555043ac99250e583d5baeb7a89a2133365d72ad5bead7037c`. It received bounded artifact-integrity comments but no eligible approval. Any later commit supersedes that exact-head evidence; no result transfers to the successor.
''',
        '''PR #114 remains the adoption root targeting `main`. PR #125 is the active stacked source review on `codex/hepta-identity-migration-20260910`, and `docs/CURRENT_CANDIDATE.json` is its machine-readable pointer. The live GitHub API is authoritative for head, tree, Draft state, jobs, Artifact and reviews; copied moving-object facts are descriptive only and cannot authorize admission.

The active successor remains `source_implemented`. It requires a fresh seven-job result, exact-head Artifact inspection and eligible independent Code Owner approval on one unchanged final head. No execution or approval from PR #114, #117, a one-shot repair workflow or another predecessor transfers to it.
''',
        "CURRENT_STATE live candidate truth",
    )
    current_path.write_text(current, encoding="utf-8")

    project_path = ROOT / "docs/PROJECT_STATE.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    project["source_authority"]["branch"] = (
        "codex/hepta-identity-migration-20260910"
    )
    project["source_authority"]["pull_request"] = 125
    project["source_authority"]["identity_rule"] = (
        "live_pull_request_head_and_tree"
    )
    project["repository_actionable_gate"]["module_registry"] = (
        "docs/modules/modules.json"
    )
    project["repository_actionable_gate"]["module_handoff"] = (
        "docs/modules/README.md"
    )
    project_path.write_text(
        json.dumps(project, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    candidate = {
        "schema_version": 1,
        "repository": "TrillionniumFoundation/hepta-glasses",
        "adoption_pull_request": 114,
        "active_review_pull_request": 125,
        "branch": "codex/hepta-identity-migration-20260910",
        "identity_rule": "live_pull_request_head_and_tree",
        "maturity": "source_implemented",
        "source_frozen": False,
        "copied_sha_is_authoritative": False,
        "evidence_transfer_allowed": False,
        "required_jobs": [
            "repository-contracts",
            "flutter",
            "android-native",
            "ios-native",
            "native-sanitizers",
            "secret-and-boundary-scan",
            "source-evidence",
        ],
        "external_authority_complete": False,
        "claim_ceiling": (
            "repository source only; live GitHub and real external authorities "
            "remain required"
        ),
    }
    (ROOT / "docs/CURRENT_CANDIDATE.json").write_text(
        json.dumps(candidate, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    truth_path = ROOT / "services/qualification/documentation_truth_core.py"
    truth = truth_path.read_text(encoding="utf-8")
    truth = exact(
        truth,
        'EXPECTED_REPOSITORY = "TrillionniumFoundation/hepta-glasses"\n',
        'EXPECTED_REPOSITORY = "TrillionniumFoundation/hepta-glasses"\n'
        'EXPECTED_ADOPTION_PULL_REQUEST = 114\n'
        'EXPECTED_ACTIVE_REVIEW_PULL_REQUEST = 125\n'
        'EXPECTED_ACTIVE_REVIEW_BRANCH = '
        '"codex/hepta-identity-migration-20260910"\n',
        "documentation truth active review constants",
    )
    truth = exact(
        truth,
        '    "final unchanged head still requires a fresh complete seven-lane result",\n',
        '    "final unchanged head still requires a fresh complete seven-lane result",\n'
        '    "it is out of Draft",\n',
        "documentation stale Draft claim",
    )
    truth = exact(
        truth,
        '    project = read_object(root, "docs/PROJECT_STATE.json")\n'
        '    implementation = read_object(root, "docs/HG0087_IMPLEMENTATION_STATUS.json")\n',
        '    project = read_object(root, "docs/PROJECT_STATE.json")\n'
        '    candidate = read_object(root, "docs/CURRENT_CANDIDATE.json")\n'
        '    implementation = read_object(root, "docs/HG0087_IMPLEMENTATION_STATUS.json")\n',
        "read current candidate pointer",
    )
    validation = '''    expected_candidate_keys = {
        "schema_version",
        "repository",
        "adoption_pull_request",
        "active_review_pull_request",
        "branch",
        "identity_rule",
        "maturity",
        "source_frozen",
        "copied_sha_is_authoritative",
        "evidence_transfer_allowed",
        "required_jobs",
        "external_authority_complete",
        "claim_ceiling",
    }
    require_exact_keys(candidate, expected_candidate_keys, label="CURRENT_CANDIDATE")
    if candidate.get("schema_version") != 1:
        fail("CURRENT_CANDIDATE schema version drifted")
    if candidate.get("repository") != EXPECTED_REPOSITORY:
        fail("CURRENT_CANDIDATE repository drifted")
    if candidate.get("adoption_pull_request") != EXPECTED_ADOPTION_PULL_REQUEST:
        fail("CURRENT_CANDIDATE adoption PR drifted")
    if candidate.get("active_review_pull_request") != EXPECTED_ACTIVE_REVIEW_PULL_REQUEST:
        fail("CURRENT_CANDIDATE active review PR drifted")
    if candidate.get("branch") != EXPECTED_ACTIVE_REVIEW_BRANCH:
        fail("CURRENT_CANDIDATE branch drifted")
    if candidate.get("identity_rule") != "live_pull_request_head_and_tree":
        fail("CURRENT_CANDIDATE permits copied identity")
    if candidate.get("maturity") != "source_implemented":
        fail("CURRENT_CANDIDATE overclaims maturity")
    if not isinstance(candidate.get("source_frozen"), bool):
        fail("CURRENT_CANDIDATE source_frozen must be boolean")
    if candidate.get("copied_sha_is_authoritative") is not False:
        fail("CURRENT_CANDIDATE permits self-attested SHA authority")
    if candidate.get("evidence_transfer_allowed") is not False:
        fail("CURRENT_CANDIDATE permits predecessor evidence transfer")
    if tuple(candidate.get("required_jobs", ())) != EXPECTED_REQUIRED_JOBS:
        fail("CURRENT_CANDIDATE required jobs drifted")
    if candidate.get("external_authority_complete") is not False:
        fail("CURRENT_CANDIDATE manufactures external authority")
    require_string(
        candidate.get("claim_ceiling"),
        label="CURRENT_CANDIDATE.claim_ceiling",
    )

'''
    truth = exact(
        truth,
        '    require_exact_keys(project, PROJECT_KEYS, label="PROJECT_STATE")\n',
        validation
        + '    require_exact_keys(project, PROJECT_KEYS, label="PROJECT_STATE")\n',
        "validate current candidate pointer",
    )
    truth = exact(
        truth,
        '''    if source_authority.get("repository") != EXPECTED_REPOSITORY:
        fail("source authority repository drifted")
''',
        '''    if source_authority.get("repository") != EXPECTED_REPOSITORY:
        fail("source authority repository drifted")
    if source_authority.get("pull_request") != EXPECTED_ACTIVE_REVIEW_PULL_REQUEST:
        fail("source authority active review PR drifted")
    if source_authority.get("branch") != EXPECTED_ACTIVE_REVIEW_BRANCH:
        fail("source authority active review branch drifted")
    if source_authority.get("identity_rule") != "live_pull_request_head_and_tree":
        fail("source authority identity rule drifted")
''',
        "bind project state to active review pointer",
    )
    truth = exact(
        truth,
        '''        require_phrase(text, "HG-0087 is `CLOSED_SOURCE`", document=relative)
        require_phrase(text, PINNED_BASELINE["commit"], document=relative)
''',
        '''        require_phrase(text, "HG-0087 is `CLOSED_SOURCE`", document=relative)
        require_phrase(text, "PR #125", document=relative)
        require_phrase(
            text,
            "live GitHub API is authoritative",
            document=relative,
        )
        require_phrase(
            text,
            "docs/CURRENT_CANDIDATE.json",
            document=relative,
        )
        require_phrase(text, PINNED_BASELINE["commit"], document=relative)
''',
        "require live candidate truth in prose",
    )
    truth_path.write_text(truth, encoding="utf-8")

    index_path = ROOT / "docs/README.md"
    index = index_path.read_text(encoding="utf-8")
    index = exact(
        index,
        "1. `CURRENT_STATE.md` — current source, governance, platform, and external-authority truth.\n",
        "1. `CURRENT_CANDIDATE.json` — live-review pointer; moving head/tree/check/review facts come from GitHub.\n"
        "2. `CURRENT_STATE.md` — current source, governance, platform, and external-authority truth.\n",
        "documentation index candidate pointer",
    )
    index_path.write_text(index, encoding="utf-8")


def cleanup() -> None:
    for relative in (
        ".github/workflows/source-truth-closure-once.yml",
        "tools/one_shot_source_truth.py",
    ):
        path = ROOT / relative
        if path.exists():
            path.unlink()


def main() -> int:
    close_dependency_policy()
    close_module_semantics()
    close_candidate_truth()
    cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
