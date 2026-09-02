#!/usr/bin/env python3
"""Fail closed when test mutation authority enters the product build graph."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_PRODUCT_TOKENS = (
    "HEPTA_ALLOW_DEVELOPMENT_AUTHORITY",
    "DevelopmentMutationAuthorityProvider",
    "explicit-development-build-flag",
    "development_build_flag",
    "dev-lease-",
    "development-user",
    "development-g1-pair",
    "TestMutationAuthorityProvider",
    "test-only-authority",
    "test-lease-",
)


def fail(message: str) -> None:
    raise AssertionError(message)


def product_dart_sources() -> list[Path]:
    return sorted(path for path in (ROOT / "lib").rglob("*.dart") if path.is_file())


def validate_product_graph() -> None:
    violations: list[str] = []
    for path in product_dart_sources():
        source = path.read_text(encoding="utf-8")
        for token in FORBIDDEN_PRODUCT_TOKENS:
            if token in source:
                violations.append(f"{path.relative_to(ROOT)}:{token}")
        if "../test/" in source or "package:demo_ai_even/test/" in source:
            violations.append(f"{path.relative_to(ROOT)}:test_import")
    if violations:
        fail("test/development mutation authority reached lib/: " + ", ".join(violations))


def validate_production_entrypoint() -> None:
    main = (ROOT / "lib/main.dart").read_text(encoding="utf-8")
    bootstrap = (ROOT / "lib/bootstrap/hepta_bootstrap.dart").read_text(
        encoding="utf-8"
    )
    runtime_authority = (ROOT / "lib/runtime/mutation_authority.dart").read_text(
        encoding="utf-8"
    )

    required_main = (
        "mutationAuthority: const FailClosedMutationAuthorityProvider(),",
        "checkpointAuthenticator: const PlatformAuditCheckpointAuthenticator(),",
    )
    if any(fragment not in main for fragment in required_main):
        fail("production main does not explicitly bind fail-closed authority")
    if "required MutationAuthorityProvider mutationAuthority" not in bootstrap:
        fail("composition root does not require explicit mutation authority injection")
    if "FailClosedMutationAuthorityProvider" not in runtime_authority:
        fail("production fail-closed authority implementation is missing")
    if "Clock" in runtime_authority or "DecisionLease(" in runtime_authority:
        fail("production authority module can still synthesize a lease")


def validate_test_separation() -> None:
    test_authority = ROOT / "test/support/test_mutation_authority.dart"
    boundary_test = ROOT / "test/runtime/production_authority_boundary_test.dart"
    if not test_authority.is_file() or not boundary_test.is_file():
        fail("test-only authority or product-boundary regression is missing")
    source = test_authority.read_text(encoding="utf-8")
    if "TestMutationAuthorityProvider" not in source or "DecisionLease(" not in source:
        fail("test-only authority does not provide deterministic lease coverage")


def validate_ci_release_proof() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    required = (
        "python3 tools/validate_production_authority.py",
        "Build Android release graph",
        "Inspect Android release binary for test-only authority",
        "flutter build ios --release --no-codesign",
        "Inspect iOS release binary for test-only authority",
    )
    if any(fragment not in workflow for fragment in required):
        fail("CI lacks production authority release-build or binary-absence proof")
    if "--dart-define=HEPTA_ALLOW_DEVELOPMENT_AUTHORITY" in workflow:
        fail("CI can still request the removed development authority switch")
    if "- 'codex/**'" in workflow or '- "codex/**"' in workflow:
        fail("CI duplicates pull_request matrices with codex-branch push matrices")
    if "pull_request:" not in workflow or "push:\n    branches:\n      - main" not in workflow:
        fail("CI trigger authority must be pull_request for PRs and push for main only")

    try:
        concurrency = workflow.split("concurrency:\n", 1)[1].split("\njobs:\n", 1)[0]
    except IndexError:
        fail("CI lacks an explicit concurrency custody block")
    required_concurrency = (
        "group: hepta-glasses-${{ github.workflow }}-"
        "${{ github.event.pull_request.number || github.ref_name }}"
    )
    if required_concurrency not in concurrency or "cancel-in-progress: true" not in concurrency:
        fail("CI does not cancel obsolete runs for the same pull request or branch")
    if "github.event.pull_request.head.sha" in concurrency or "github.sha" in concurrency:
        fail("CI concurrency is keyed by commit SHA and cannot cancel obsolete PR heads")


def main() -> int:
    validate_product_graph()
    validate_production_entrypoint()
    validate_test_separation()
    validate_ci_release_proof()
    print(
        json.dumps(
            {
                "ok": True,
                "product_dart_files": len(product_dart_sources()),
                "production_authority": "fail_closed_only",
                "test_authority_location": "test/support/test_mutation_authority.dart",
                "release_binary_absence_checks": ["android", "ios"],
                "ci_pr_trigger": "pull_request_only",
                "ci_main_trigger": "push_only",
                "ci_concurrency": "latest_pull_request_or_branch_only",
                "exact_head_identity": "verified_inside_every_job",
            },
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as error:
        print(json.dumps({"ok": False, "error": str(error)}, separators=(",", ":")))
        raise SystemExit(1)
