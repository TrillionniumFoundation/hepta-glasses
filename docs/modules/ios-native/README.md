# `ios-native` module engineering handoff

Canonical registry digest: `a5dfc1065fcb6d6f6eedc6a0d0c3a985ce3a4991363eb346c5ffa35c6e619cd7`

Owner: `ios`

Lifecycle: `source_candidate`

Profile: `engineering-handoff-v1`

This generated handoff is a module-specific navigation and consistency surface. It does not replace the owner-authored primary document `docs/MODULE_DEVELOPMENT_GUIDE.md#ios-native` or manufacture deployment, physical-device, provider, signing, assurance, pilot, store, or release evidence.

## 1. Purpose and authority boundary

The module identifier is `ios-native` and its accountable owner is `ios`. Its current platform state is:

> iOS device and simulator builds; speech depends on permission, locale and device capability.

Implementation authority is limited to the source roots listed below. Anything outside those roots requires an explicit registry change and owner review. External gates remain non-source authorities and are never inferred from a green repository test.

### Source roots

- `ios/Runner`
- `ios/Runner.xcodeproj`
- `ios`

## 2. Public interfaces and contracts

The primary engineering description is `docs/MODULE_DEVELOPMENT_GUIDE.md#ios-native`. The following contracts are the machine-readable interface and compatibility boundary for this module:

- `contracts/g1-ble-protocol-v1.json`
- `docs/PLATFORM_CAPABILITIES.json`

The following documentation forms the reviewed human interface. A contract, schema, command, channel, API, storage layout, or externally visible behavior change must update every affected reference in the same candidate:

- `docs/MODULE_DEVELOPMENT_GUIDE.md#ios-native`
- `docs/G1_BLE_CONNECTION.md`
- `docs/development/MODULE_HANDOFF.md#ios-native`

## 3. State, concurrency, and cancellation

State ownership, concurrency, cancellation, generation fencing, idempotency, and late-result behavior are defined jointly by the primary document, the registered source roots, and the contracts above. A change is inadmissible when those surfaces disagree. Unknown state, stale generation, expired authority, ambiguous ownership, or cancellation races must fail closed rather than silently commit a side effect.

## 4. Failure, recovery, and idempotency

The module must preserve explicit pre-effect failure, indeterminate-after-possible-effect, authoritative readback, retry, replay, and recovery semantics documented by its contracts. Recovery must not widen authority, restore revoked state, reuse a conflicting idempotency key, or convert missing evidence into success. Cross-module recovery changes require review from every affected owner.

## 5. Configuration, compatibility, and migration

Configuration and migration are source objects. Dependency, toolchain, schema, provider, platform, package identity, storage, policy, or firmware movement requires compatibility analysis and fresh qualification for the affected evidence axes. No historical Artifact, approval, physical report, provider receipt, signature, or release decision automatically transfers to a successor.

## 6. Operations, tests, observability, and SLO

The registered executable verification surfaces are:

- `ios/RunnerTests/RunnerTests.swift`
- `test/runtime/ios_speech_finalization_contract_test.dart`
- `services/qualification/test_ios_ci.py`

Tests prove only their declared environment and assertions. Operational acceptance additionally requires bounded logs, privacy-safe traces, stable error classes, relevant SLO measurements, rollback/recovery procedures, and exact candidate identity. Module owners must record negative-path evidence, not only successful examples.

## 7. Security, privacy, and evidence ceiling

The current evidence ceiling is:

> Simulator/XCTest does not establish signed-device, App Attest, battery, thermal, locale matrix or physical G1 qualification.

The unresolved external or authority-owned boundaries are:

- physical G1, locale/device speech qualification, App Attest and release signing

Secrets, raw credentials, signing material, unrestricted mutation authority, and sensitive user content must not be introduced into source, prompts, ordinary logs, generated documentation, test fixtures that escape their boundary, or repository evidence packages.

## 8. Ownership and change protocol

A change touching a listed source root, contract, test, or primary document must update the canonical module record when ownership, interfaces, platform state, evidence ceiling, or external gates change. Run `python3 tools/generate_module_docs.py --check` and `python3 tools/validate_module_semantics.py`; obtain the applicable Code Owner review; run all seven canonical CI jobs on one unchanged head; and bind any promotion to fresh exact-head evidence. Administrator bypass, self-review, stale evidence reuse, or generated prose alone cannot approve the change.
