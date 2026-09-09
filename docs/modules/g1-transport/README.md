# `g1-transport` module engineering handoff

Canonical registry digest: `3182d1f41a0b4628389f7bd726af4920ab3531f798ce5f1e8a7997df288fea9b`

Owner: `device`

Lifecycle: `source_candidate`

Profile: `engineering-handoff-v1`

This generated handoff is a module-specific navigation and consistency surface. It does not replace the owner-authored primary document `docs/MODULE_DEVELOPMENT_GUIDE.md#g1-transport` or manufacture deployment, physical-device, provider, signing, assurance, pilot, store, or release evidence.

## 1. Purpose and authority boundary

The module identifier is `g1-transport` and its accountable owner is `device`. Its current platform state is:

> Android and iOS implementations retain separate callback models but the same public authority identity.

Implementation authority is limited to the source roots listed below. Anything outside those roots requires an explicit registry change and owner review. External gates remain non-source authorities and are never inferred from a green repository test.

### Source roots

- `lib/ble_manager.dart`
- `lib/adapters/even_g1`
- `lib/runtime/ble_request_slot.dart`
- `lib/runtime/device_hal.dart`
- `lib/runtime/dual_leg_coordinator.dart`
- `lib/services/ble.dart`
- `android/app/src/main/kotlin/com/example/demo_ai_even/bluetooth`
- `ios/Runner/BluetoothManager.swift`

## 2. Public interfaces and contracts

The primary engineering description is `docs/MODULE_DEVELOPMENT_GUIDE.md#g1-transport`. The following contracts are the machine-readable interface and compatibility boundary for this module:

- `contracts/g1-ble-protocol-v1.json`
- `schemas/glasses-event.schema.json`

The following documentation forms the reviewed human interface. A contract, schema, command, channel, API, storage layout, or externally visible behavior change must update every affected reference in the same candidate:

- `docs/G1_BLE_CONNECTION.md`
- `docs/MODULE_DEVELOPMENT_GUIDE.md#g1-transport`
- `docs/development/MODULE_HANDOFF.md#g1-transport`

## 3. State, concurrency, and cancellation

State ownership, concurrency, cancellation, generation fencing, idempotency, and late-result behavior are defined jointly by the primary document, the registered source roots, and the contracts above. A change is inadmissible when those surfaces disagree. Unknown state, stale generation, expired authority, ambiguous ownership, or cancellation races must fail closed rather than silently commit a side effect.

## 4. Failure, recovery, and idempotency

The module must preserve explicit pre-effect failure, indeterminate-after-possible-effect, authoritative readback, retry, replay, and recovery semantics documented by its contracts. Recovery must not widen authority, restore revoked state, reuse a conflicting idempotency key, or convert missing evidence into success. Cross-module recovery changes require review from every affected owner.

## 5. Configuration, compatibility, and migration

Configuration and migration are source objects. Dependency, toolchain, schema, provider, platform, package identity, storage, policy, or firmware movement requires compatibility analysis and fresh qualification for the affected evidence axes. No historical Artifact, approval, physical report, provider receipt, signature, or release decision automatically transfers to a successor.

## 6. Operations, tests, observability, and SLO

The registered executable verification surfaces are:

- `test/runtime/ble_manager_authority_test.dart`
- `test/runtime/ble_request_slot_test.dart`
- `test/runtime/even_g1_transport_authority_test.dart`
- `test/runtime/dual_leg_coordinator_test.dart`
- `ios/RunnerTests/RunnerTests.swift`
- `android/app/src/test/kotlin/com/example/demo_ai_even/model/BlePairDeviceTest.kt`

Tests prove only their declared environment and assertions. Operational acceptance additionally requires bounded logs, privacy-safe traces, stable error classes, relevant SLO measurements, rollback/recovery procedures, and exact candidate identity. Module owners must record negative-path evidence, not only successful examples.

## 7. Security, privacy, and evidence ceiling

The current evidence ceiling is:

> Hostile source tests do not prove RF behavior, physical protocol compatibility, latency, power, thermal, soak or vendor authority.

The unresolved external or authority-owned boundaries are:

- physical Android/iOS G1 qualification and vendor protocol authority

Secrets, raw credentials, signing material, unrestricted mutation authority, and sensitive user content must not be introduced into source, prompts, ordinary logs, generated documentation, test fixtures that escape their boundary, or repository evidence packages.

## 8. Ownership and change protocol

A change touching a listed source root, contract, test, or primary document must update the canonical module record when ownership, interfaces, platform state, evidence ceiling, or external gates change. Run `python3 tools/generate_module_docs.py --check` and `python3 tools/validate_module_semantics.py`; obtain the applicable Code Owner review; run all seven canonical CI jobs on one unchanged head; and bind any promotion to fresh exact-head evidence. Administrator bypass, self-review, stale evidence reuse, or generated prose alone cannot approve the change.
