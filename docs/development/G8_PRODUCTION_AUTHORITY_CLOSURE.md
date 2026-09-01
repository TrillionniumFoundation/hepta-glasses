# G8 production mutation-authority closure

Date: 2026-09-02
Plan revision: `2026-09-01-g8`
Review origin: independent CODEOWNER P1 finding on PR #23

## Finding

The prior mobile bootstrap selected `DevelopmentMutationAuthorityProvider` from the forgeable Dart define `HEPTA_ALLOW_DEVELOPMENT_AUTHORITY`. That provider synthesized authenticated and user-present policy context plus exact single-use leases. A release-shaped application could therefore include a local authority path without platform identity or attestation.

## Closed source design

The product dependency graph now has only the `MutationAuthorityProvider` interface and `FailClosedMutationAuthorityProvider`. `lib/main.dart` explicitly injects the fail-closed provider, and `HeptaBootstrap.initialize` requires its caller to supply a provider instead of selecting one from an environment or Dart define. No product source can construct a `DecisionLease`.

Deterministic lease tests use `TestMutationAuthorityProvider` from `test/support/test_mutation_authority.dart`. Nothing under `lib/` imports `test/`, and the test provider, its proof strings, and its lease identifiers are forbidden in production artifacts.

## Fail-closed verification

`test/runtime/production_authority_boundary_test.dart` scans every Dart file under `lib/` and rejects the removed flag, provider, lease and test-authority tokens. It also verifies explicit fail-closed injection at the process entry point and explicit authority injection at the composition root.

`tools/validate_production_authority.py` independently enforces the same product graph, entry-point and test-separation rules. The repository-contracts lane executes it on the exact head.

The Android lane builds the debug application, runs `assembleRelease`, expands the release APK and rejects every forbidden authority token from the resulting files. The iOS lane builds both debug and release simulator applications and rejects the same tokens from the release `App.framework` binary. Both lanes remain read-only and exact-head bound.

## Single exact-head CI authority

PR branches execute the canonical workflow through the `pull_request` event only. The `push` trigger is restricted to `main`. This prevents a branch push and the associated PR synchronization event from launching two matrices with the same concurrency identity and cancelling one another mid-lane. `tools/validate_production_authority.py` fails if a `codex/**` push trigger is reintroduced.

## Evidence ceiling

These checks close the repository-actionable escape hatch and establish E1-E4 source/build evidence after exact-head CI succeeds. They do not supply production identity, KMS/HSM, Apple/Android attestation, physical-device qualification, signed store binaries, pilot or independent release approval. Until those external gates close, production mutation requests remain fail closed.
