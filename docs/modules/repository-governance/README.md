# `repository-governance` module engineering handoff

Canonical registry digest: `7415e124284fb6574b316719377e42634618c22d69087303ac203fe36241d582`

Owner: `repository-admin`

Lifecycle: `source_candidate`

Profile: `engineering-handoff-v1`

This generated handoff is a module-specific navigation and consistency surface. It does not replace the owner-authored primary document `docs/MODULE_DEVELOPMENT_GUIDE.md#repository-governance` or manufacture deployment, physical-device, provider, signing, assurance, pilot, store, or release evidence.

## 1. Purpose and authority boundary

The module identifier is `repository-governance` and its accountable owner is `repository-admin`. Its current platform state is:

> GitHub repository governance plus deterministic local validators.

Implementation authority is limited to the source roots listed below. Anything outside those roots requires an explicit registry change and owner review. External gates remain non-source authorities and are never inferred from a green repository test.

### Source roots

- `.github`
- `tools/repository_governance.py`
- `docs/GAP_LEDGER.yaml`
- `docs/EVIDENCE_INDEX.yaml`
- `docs/MODULES.json`
- `tools/validate_source_coverage.py`
- `tools/repository_snapshot.py`
- `docs/MODULE_COVERAGE.json`
- `tools/validate_module_handoff.py`
- `docs/MODULE_HANDOFF.json`
- `tools/server_provider_boundary.py`
- `tools/generate_module_docs.py`
- `tools/validate_module_semantics.py`

## 2. Public interfaces and contracts

The primary engineering description is `docs/MODULE_DEVELOPMENT_GUIDE.md#repository-governance`. The following contracts are the machine-readable interface and compatibility boundary for this module:

- `contracts/main-branch-protection-v1.json`
- `contracts/server-provider-boundary-v1.json`

The following documentation forms the reviewed human interface. A contract, schema, command, channel, API, storage layout, or externally visible behavior change must update every affected reference in the same candidate:

- `docs/MODULE_DEVELOPMENT_GUIDE.md#repository-governance`
- `docs/operations/REPOSITORY_GOVERNANCE_RUNBOOK.md`
- `docs/development/SOURCE_COVERAGE_AND_STATE.md`
- `docs/development/2026-09-03_BLOCKER_EXECUTION_PLAN.md`
- `docs/development/MODULE_HANDOFF.md#repository-governance`
- `docs/development/MODULE_HANDOFF.md`
- `docs/development/SERVER_PROVIDER_BOUNDARY.md`
- `docs/modules/README.md`
- `docs/modules/modules.json`

## 3. State, concurrency, and cancellation

State ownership, concurrency, cancellation, generation fencing, idempotency, and late-result behavior are defined jointly by the primary document, the registered source roots, and the contracts above. A change is inadmissible when those surfaces disagree. Unknown state, stale generation, expired authority, ambiguous ownership, or cancellation races must fail closed rather than silently commit a side effect.

## 4. Failure, recovery, and idempotency

The module must preserve explicit pre-effect failure, indeterminate-after-possible-effect, authoritative readback, retry, replay, and recovery semantics documented by its contracts. Recovery must not widen authority, restore revoked state, reuse a conflicting idempotency key, or convert missing evidence into success. Cross-module recovery changes require review from every affected owner.

## 5. Configuration, compatibility, and migration

Configuration and migration are source objects. Dependency, toolchain, schema, provider, platform, package identity, storage, policy, or firmware movement requires compatibility analysis and fresh qualification for the affected evidence axes. No historical Artifact, approval, physical report, provider receipt, signature, or release decision automatically transfers to a successor.

## 6. Operations, tests, observability, and SLO

The registered executable verification surfaces are:

- `services/qualification/test_governance.py`
- `tools/validate_repository.py`
- `tools/validate_repository_metadata.py`
- `services/qualification/test_source_coverage.py`
- `services/qualification/test_module_handoff.py`
- `services/qualification/test_handoff_status_drift.py`
- `services/qualification/test_server_provider_boundary.py`
- `services/qualification/test_calendar_provider_boundary.py`
- `services/qualification/test_module_semantic_docs.py`

Tests prove only their declared environment and assertions. Operational acceptance additionally requires bounded logs, privacy-safe traces, stable error classes, relevant SLO measurements, rollback/recovery procedures, and exact candidate identity. Module owners must record negative-path evidence, not only successful examples.

## 7. Security, privacy, and evidence ceiling

The current evidence ceiling is:

> Source cannot apply/read inaccessible administrator settings, issue an independent review or merge itself.

The unresolved external or authority-owned boundaries are:

- administrator-applied and API-verified branch protection plus eligible latest-head approval

Secrets, raw credentials, signing material, unrestricted mutation authority, and sensitive user content must not be introduced into source, prompts, ordinary logs, generated documentation, test fixtures that escape their boundary, or repository evidence packages.

## 8. Ownership and change protocol

A change touching a listed source root, contract, test, or primary document must update the canonical module record when ownership, interfaces, platform state, evidence ceiling, or external gates change. Run `python3 tools/generate_module_docs.py --check` and `python3 tools/validate_module_semantics.py`; obtain the applicable Code Owner review; run all seven canonical CI jobs on one unchanged head; and bind any promotion to fresh exact-head evidence. Administrator bypass, self-review, stale evidence reuse, or generated prose alone cannot approve the change.
