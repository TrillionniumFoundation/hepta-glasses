#!/usr/bin/env python3
"""Fail closed when forgeable mutation authority enters the product graph."""

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
    authority = (ROOT / "lib/runtime/mutation_authority.dart").read_text(
        encoding="utf-8"
    )

    required_main = (
        "MutationAuthorityBootstrap.configureFromEnvironment();",
        "mutationAuthority: MutationAuthorityRegistry.current,",
        "checkpointAuthenticator: const PlatformAuditCheckpointAuthenticator(),",
    )
    if any(fragment not in main for fragment in required_main):
        fail("production main does not bind the authenticated authority registry")
    if "required MutationAuthorityProvider mutationAuthority" not in bootstrap:
        fail("composition root does not require explicit mutation authority injection")

    required_authority = (
        "class FailClosedMutationAuthorityProvider",
        "class HttpMutationAuthorityProvider",
        "class MutationAccessTokenRegistry",
        "class RegistryMutationAccessTokenProvider",
        "HEPTA_MUTATION_AUTHORITY_URL",
        "HEPTA_MUTATION_AUTHORITY_DEV_TOKEN",
        "product && developmentToken.isNotEmpty",
        "compiled_mutation_token_forbidden_in_product",
        "mutation_authority_unauthenticated",
        "mutation_authority_response_invalid",
        "source: 'identity_https'",
        "followRedirects: false",
        "maxRedirects: 0",
        "expectedArgumentDigest",
        "expiresAt.isAfter(request.deadline)",
        "request.riskTier == RiskTier.r4",
    )
    if any(fragment not in authority for fragment in required_authority):
        fail("production mutation authority lost an authenticated fail-closed invariant")

    constructors = authority.count("DecisionLease(")
    if constructors != 1:
        fail("production authority must have exactly one response-bound lease constructor")
    decode_index = authority.find("static MutationAuthorization decodeAuthorization(")
    constructor_index = authority.find("DecisionLease(")
    if decode_index < 0 or constructor_index < decode_index:
        fail("production lease can be constructed outside strict HTTPS response decoding")
    if "Deterministic" in authority or "Clock" in authority:
        fail("production authority contains a deterministic local lease source")


def validate_server_authority() -> None:
    source = (ROOT / "services/control_plane/mutation_authority.py").read_text(
        encoding="utf-8"
    )
    required = (
        "class MutationLeaseAuthority",
        "BEGIN IMMEDIATE",
        "mutation_authority_policy",
        "mutation_revocations",
        "argument_digest",
        "DEFAULT_ACTION_POLICY",
        "mutation_authority_user_presence_required",
        "mutation_authority_biometric_required",
        "mutation_authority_policy_migration_required",
        '"state TEXT NOT NULL CHECK(state IN (\'issued\',\'revoked\'))"',
    )
    if any(fragment not in source for fragment in required):
        fail("server mutation authority lost durable policy/revocation custody")
    prohibited = (
        "client_verified",
        "development-user",
        "test-lease-",
        "INSERT INTO mutation_leases VALUES",
    )
    if any(fragment in source for fragment in prohibited):
        fail("server mutation authority contains a forgeable or positional path")


def validate_test_separation() -> None:
    test_authority = ROOT / "test/support/test_mutation_authority.dart"
    boundary_test = ROOT / "test/runtime/production_authority_boundary_test.dart"
    mobile_test = ROOT / "test/runtime/mutation_authority_test.dart"
    server_test = ROOT / "services/control_plane/test_mutation_authority.py"
    if not all(path.is_file() for path in (
        test_authority,
        boundary_test,
        mobile_test,
        server_test,
    )):
        fail("mutation authority boundary or source integration regression is missing")
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
    validate_server_authority()
    validate_test_separation()
    validate_ci_release_proof()
    print(
        json.dumps(
            {
                "ok": True,
                "product_dart_files": len(product_dart_sources()),
                "production_authority": "authenticated_https_or_fail_closed",
                "runtime_token_source": "dynamic_registry_no_compiled_product_token",
                "server_lease_custody": "durable_exact_argument_policy_and_revocation",
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
