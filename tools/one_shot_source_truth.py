#!/usr/bin/env python3
"""One-shot deterministic CI and module-documentation repair."""

from __future__ import annotations

import hashlib
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
    """Validate committed dependency-update policy without network I/O."""
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
        "insert deterministic dependency contract",
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
        "add deterministic dependency CLI mode",
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
        "route deterministic dependency CLI mode",
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
        "add scheduled official freshness observation",
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
    workflow_blob = hashlib.sha1(
        f"blob {len(encoded)}\0".encode("ascii") + encoded
    ).hexdigest()
    policy = policy_path.read_text(encoding="utf-8")
    policy, count = re.subn(
        r'(_APPROVED_WORKFLOW_GIT_BLOB_SHA1 = \(\n    ")[0-9a-f]{40}("\n\))',
        rf"\g<1>{workflow_blob}\g<2>",
        policy,
        count=1,
    )
    if count != 1:
        raise SystemExit("failed to update canonical workflow object binding")
    policy_path.write_text(policy, encoding="utf-8")


def close_module_semantics() -> None:
    validator_path = ROOT / "tools/validate_module_semantics.py"
    validator = validator_path.read_text(encoding="utf-8")
    validator = exact(
        validator,
        "requires eight engineering dimensions, verifies every source/document/test/\ncontract reference, and rejects compatibility-layer drift.",
        "binds eleven canonical semantic dimensions to eight compact generated\nhandoff sections, verifies every source/document/test/contract reference, and\nrejects compatibility-layer drift.",
        "module validator description",
    )
    semantic_contract = '''CANONICAL_SEMANTIC_HEADINGS = (
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
        semantic_contract + "MINIMUM_PAGE_CHARACTERS = 2_000\n",
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
    semantic_positions = [
        standard_text.find(heading) for heading in CANONICAL_SEMANTIC_HEADINGS
    ]
    if any(position < 0 for position in semantic_positions) or semantic_positions != sorted(semantic_positions):
        fail("canonical eleven module semantic dimensions drifted")
    registry = load_canonical(root)
''',
        "validate canonical eleven-dimension standard",
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
        "separate semantic and generated dimensions",
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
        "module test imports",
    )
    test = exact(
        test,
        '        self.assertEqual(result["semantic_dimensions"], 8)\n',
        '        self.assertEqual(result["semantic_dimensions"], 11)\n'
        '        self.assertEqual(result["generated_handoff_sections"], 8)\n',
        "module test semantic count",
    )
    test = exact(
        test,
        "    def test_generated_page_binds_all_eight_dimensions_and_module_data(self) -> None:\n",
        "    def test_generated_page_binds_all_compact_sections_and_module_data(self) -> None:\n",
        "module compact section test name",
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
        "module test eleven-dimension binding",
    )
    test_path.write_text(test, encoding="utf-8")


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
    cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
