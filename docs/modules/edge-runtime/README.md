# `edge-runtime` module engineering handoff

Canonical registry digest: `066e781cfc302531f4fae3737bf061113797f3da08a07dceb9d18e2c2a4909e4`

Owner: `runtime`

Lifecycle: `source_candidate`

Profile: `engineering-handoff-v1`

This generated handoff is a module-specific navigation and consistency surface. It does not replace the owner-authored primary document `docs/MODULE_DEVELOPMENT_GUIDE.md#edge-runtime` or manufacture deployment, physical-device, provider, signing, assurance, pilot, store, or release evidence.

## 1. Purpose and authority boundary

The module identifier is `edge-runtime` and its accountable owner is `runtime`. Its current platform state is:

> Runs in the Flutter edge process on both mobile platforms; physical effects are delegated to platform adapters.

Implementation authority is limited to the source roots listed below. Anything outside those roots requires an explicit registry change and owner review. External gates remain non-source authorities and are never inferred from a green repository test.

### Source roots

- `lib/runtime/hepta_runtime.dart`
- `lib/runtime/task_engine.dart`
- `lib/runtime/device_effect_scheduler.dart`
- `lib/runtime/display_composer.dart`
- `lib/runtime/contracts.dart`
- `lib/runtime/canonical_json.dart`
- `lib/runtime/clock.dart`
- `lib/runtime/runtime.dart`

## 2. Public interfaces and contracts

The primary engineering description is `docs/MODULE_DEVELOPMENT_GUIDE.md#edge-runtime`. The following contracts are the machine-readable interface and compatibility boundary for this module:

- `contracts/hepta-glasses-runtime-v1.json`
- `schemas/display-card.schema.json`

The following documentation forms the reviewed human interface. A contract, schema, command, channel, API, storage layout, or externally visible behavior change must update every affected reference in the same candidate:

- `docs/MODULE_DEVELOPMENT_GUIDE.md#edge-runtime`
- `docs/development/MODULE_HANDOFF.md#edge-runtime`

## 3. State, concurrency, and cancellation

State ownership, concurrency, cancellation, generation fencing, idempotency, and late-result behavior are defined jointly by the primary document, the registered source roots, and the contracts above. A change is inadmissible when those surfaces disagree. Unknown state, stale generation, expired authority, ambiguous ownership, or cancellation races must fail closed rather than silently commit a side effect.

## 4. Failure, recovery, and idempotency

The module must preserve explicit pre-effect failure, indeterminate-after-possible-effect, authoritative readback, retry, replay, and recovery semantics documented by its contracts. Recovery must not widen authority, restore revoked state, reuse a conflicting idempotency key, or convert missing evidence into success. Cross-module recovery changes require review from every affected owner.

## 5. Configuration, compatibility, and migration

Configuration and migration are source objects. Dependency, toolchain, schema, provider, platform, package identity, storage, policy, or firmware movement requires compatibility analysis and fresh qualification for the affected evidence axes. No historical Artifact, approval, physical report, provider receipt, signature, or release decision automatically transfers to a successor.

## 6. Operations, tests, observability, and SLO

The registered executable verification surfaces are:

- `test/runtime/task_engine_test.dart`
- `test/runtime/device_effect_scheduler_test.dart`
- `test/runtime/display_composer_test.dart`

Tests prove only their declared environment and assertions. Operational acceptance additionally requires bounded logs, privacy-safe traces, stable error classes, relevant SLO measurements, rollback/recovery procedures, and exact candidate identity. Module owners must record negative-path evidence, not only successful examples.

## 7. Security, privacy, and evidence ceiling

The current evidence ceiling is:

> Deterministic E1–E3 behavior is covered; production identity, physical-effect qualification and crash recovery on signed builds remain external.

The unresolved external or authority-owned boundaries are:

- production identity-backed authority and physical effect qualification

Secrets, raw credentials, signing material, unrestricted mutation authority, and sensitive user content must not be introduced into source, prompts, ordinary logs, generated documentation, test fixtures that escape their boundary, or repository evidence packages.

## 8. Ownership and change protocol

A change touching a listed source root, contract, test, or primary document must update the canonical module record when ownership, interfaces, platform state, evidence ceiling, or external gates change. Run `python3 tools/generate_module_docs.py --check` and `python3 tools/validate_module_semantics.py`; obtain the applicable Code Owner review; run all seven canonical CI jobs on one unchanged head; and bind any promotion to fresh exact-head evidence. Administrator bypass, self-review, stale evidence reuse, or generated prose alone cannot approve the change.
