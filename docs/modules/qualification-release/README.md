# `qualification-release` module engineering handoff

Canonical registry digest: `10035cd28bba1759c85383fe7b7ca3f34cd20f784c6184ca8d78201697dc71d8`

Owner: `release`

Lifecycle: `source_candidate`

Profile: `engineering-handoff-v1`

This generated handoff is a module-specific navigation and consistency surface. It does not replace the owner-authored primary document `docs/MODULE_DEVELOPMENT_GUIDE.md#qualification-release` or manufacture deployment, physical-device, provider, signing, assurance, pilot, store, or release evidence.

## 1. Purpose and authority boundary

The module identifier is `qualification-release` and its accountable owner is `release`. Its current platform state is:

> Python qualification validates HG-0087 source closure, module ownership, external-evidence and release contracts; the canonical workflow covers repository/services, Flutter, Android, iOS, native sanitizers, boundary/history scanning and exact-head source evidence.

Implementation authority is limited to the source roots listed below. Anything outside those roots requires an explicit registry change and owner review. External gates remain non-source authorities and are never inferred from a green repository test.

### Source roots

- `services/qualification`
- `tools/qualify_device_trace.py`
- `tools/build_source_evidence.py`
- `tools/evaluate_release_gate.py`
- `tools/run_native_sanitizers.sh`
- `tools/scan_git_history.py`
- `evidence/templates`
- `services/__init__.py`
- `tools/__init__.py`
- `test`
- `tools/validate_release_version.py`
- `tools/verify_source_archive_receipt.py`
- `tools/validate_external_closure_program.py`

## 2. Public interfaces and contracts

The primary engineering description is `docs/MODULE_DEVELOPMENT_GUIDE.md#qualification-release`. The following contracts are the machine-readable interface and compatibility boundary for this module:

- `contracts/qualification-slo-v1.json`
- `contracts/release-gates-v1.json`
- `schemas/device-qualification-report.schema.json`
- `schemas/release-evidence-bundle.schema.json`
- `contracts/release-versioning-v1.json`
- `schemas/source-artifact-archive-receipt.schema.json`
- `schemas/external-closure-program.schema.json`

The following documentation forms the reviewed human interface. A contract, schema, command, channel, API, storage layout, or externally visible behavior change must update every affected reference in the same candidate:

- `docs/MODULE_DEVELOPMENT_GUIDE.md#qualification-release`
- `docs/operations/DEVICE_QUALIFICATION_RUNBOOK.md`
- `docs/operations/RELEASE_AND_ROLLBACK_RUNBOOK.md`
- `docs/development/MODULE_HANDOFF.md#qualification-release`
- `docs/development/RELEASE_VERSIONING.md`
- `docs/development/SOURCE_ARTIFACT_ARCHIVAL.md`
- `docs/EXTERNAL_CLOSURE_PROGRAM.json`
- `docs/operations/EXTERNAL_CLOSURE_ORCHESTRATION.md`

## 3. State, concurrency, and cancellation

State ownership, concurrency, cancellation, generation fencing, idempotency, and late-result behavior are defined jointly by the primary document, the registered source roots, and the contracts above. A change is inadmissible when those surfaces disagree. Unknown state, stale generation, expired authority, ambiguous ownership, or cancellation races must fail closed rather than silently commit a side effect.

## 4. Failure, recovery, and idempotency

The module must preserve explicit pre-effect failure, indeterminate-after-possible-effect, authoritative readback, retry, replay, and recovery semantics documented by its contracts. Recovery must not widen authority, restore revoked state, reuse a conflicting idempotency key, or convert missing evidence into success. Cross-module recovery changes require review from every affected owner.

## 5. Configuration, compatibility, and migration

Configuration and migration are source objects. Dependency, toolchain, schema, provider, platform, package identity, storage, policy, or firmware movement requires compatibility analysis and fresh qualification for the affected evidence axes. No historical Artifact, approval, physical report, provider receipt, signature, or release decision automatically transfers to a successor.

## 6. Operations, tests, observability, and SLO

The registered executable verification surfaces are:

- `services/qualification/test_device_report.py`
- `services/qualification/test_release_gate.py`
- `services/qualification/test_history_scan.py`
- `services/qualification/test_history_object_scope.py`
- `services/qualification/test_g10_structured_controls.py`
- `services/qualification/test_hg0087_source_status.py`
- `services/qualification/test_release_version.py`
- `services/qualification/test_source_artifact_archive_receipt.py`
- `services/qualification/test_external_closure_program.py`

Tests prove only their declared environment and assertions. Operational acceptance additionally requires bounded logs, privacy-safe traces, stable error classes, relevant SLO measurements, rollback/recovery procedures, and exact candidate identity. Module owners must record negative-path evidence, not only successful examples.

## 7. Security, privacy, and evidence ceiling

The current evidence ceiling is:

> E0–E4 never manufacture physical, deployed, independent assurance, signing, pilot or store evidence.

The unresolved external or authority-owned boundaries are:

- physical traces, independent assurance, signing, pilot, rollout, rollback and store approval

Secrets, raw credentials, signing material, unrestricted mutation authority, and sensitive user content must not be introduced into source, prompts, ordinary logs, generated documentation, test fixtures that escape their boundary, or repository evidence packages.

## 8. Ownership and change protocol

A change touching a listed source root, contract, test, or primary document must update the canonical module record when ownership, interfaces, platform state, evidence ceiling, or external gates change. Run `python3 tools/generate_module_docs.py --check` and `python3 tools/validate_module_semantics.py`; obtain the applicable Code Owner review; run all seven canonical CI jobs on one unchanged head; and bind any promotion to fresh exact-head evidence. Administrator bypass, self-review, stale evidence reuse, or generated prose alone cannot approve the change.
