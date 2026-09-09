# `g1-protocol-features` module engineering handoff

Canonical registry digest: `48121f6689c4154ad716299a1c3066347eb97867feb5917e89a0d17d907dca5c`

Owner: `device-runtime`

Lifecycle: `source_candidate`

Profile: `engineering-handoff-v1`

This generated handoff is a module-specific navigation and consistency surface. It does not replace the owner-authored primary document `docs/MODULE_DEVELOPMENT_GUIDE.md#g1-protocol-features` or manufacture deployment, physical-device, provider, signing, assurance, pilot, store, or release evidence.

## 1. Purpose and authority boundary

The module identifier is `g1-protocol-features` and its accountable owner is `device-runtime`. Its current platform state is:

> Feature orchestration is Dart; native layers provide platform transport and audio primitives.

Implementation authority is limited to the source roots listed below. Anything outside those roots requires an explicit registry change and owner review. External gates remain non-source authorities and are never inferred from a green repository test.

### Source roots

- `lib/services/proto.dart`
- `lib/services/evenai_proto.dart`
- `lib/controllers/bmp_update_manager.dart`
- `lib/services/features_services.dart`
- `lib/services/text_service.dart`
- `lib/views/features`
- `lib/runtime/packet_codec.dart`

## 2. Public interfaces and contracts

The primary engineering description is `docs/MODULE_DEVELOPMENT_GUIDE.md#g1-protocol-features`. The following contracts are the machine-readable interface and compatibility boundary for this module:

- `contracts/g1-ble-protocol-v1.json`
- `contracts/conformance/g1-packet-v1.json`

The following documentation forms the reviewed human interface. A contract, schema, command, channel, API, storage layout, or externally visible behavior change must update every affected reference in the same candidate:

- `docs/MODULE_DEVELOPMENT_GUIDE.md#g1-protocol-features`
- `docs/G1_BLE_CONNECTION.md`
- `docs/development/MODULE_HANDOFF.md#g1-protocol-features`
- `docs/development/CRITICAL_TEST_DEPTH.md`

## 3. State, concurrency, and cancellation

State ownership, concurrency, cancellation, generation fencing, idempotency, and late-result behavior are defined jointly by the primary document, the registered source roots, and the contracts above. A change is inadmissible when those surfaces disagree. Unknown state, stale generation, expired authority, ambiguous ownership, or cancellation races must fail closed rather than silently commit a side effect.

## 4. Failure, recovery, and idempotency

The module must preserve explicit pre-effect failure, indeterminate-after-possible-effect, authoritative readback, retry, replay, and recovery semantics documented by its contracts. Recovery must not widen authority, restore revoked state, reuse a conflicting idempotency key, or convert missing evidence into success. Cross-module recovery changes require review from every affected owner.

## 5. Configuration, compatibility, and migration

Configuration and migration are source objects. Dependency, toolchain, schema, provider, platform, package identity, storage, policy, or firmware movement requires compatibility analysis and fresh qualification for the affected evidence axes. No historical Artifact, approval, physical report, provider receipt, signature, or release decision automatically transfers to a successor.

## 6. Operations, tests, observability, and SLO

The registered executable verification surfaces are:

- `test/runtime/bmp_update_manager_test.dart`
- `test/runtime/heartbeat_retry_contract_test.dart`
- `test/runtime/tool_effect_semantics_test.dart`
- `test/runtime/packet_codec_test.dart`
- `test/runtime/packet_codec_contract_support.dart`
- `test/runtime/packet_codec_generated_support.dart`

Tests prove only their declared environment and assertions. Operational acceptance additionally requires bounded logs, privacy-safe traces, stable error classes, relevant SLO measurements, rollback/recovery procedures, and exact candidate identity. Module owners must record negative-path evidence, not only successful examples.

## 7. Security, privacy, and evidence ceiling

The current evidence ceiling is:

> Source validates framing and retry safety, not vendor command authority or physical display/notification behavior.

The unresolved external or authority-owned boundaries are:

- firmware command confirmation, readback support and physical display/notification qualification

Secrets, raw credentials, signing material, unrestricted mutation authority, and sensitive user content must not be introduced into source, prompts, ordinary logs, generated documentation, test fixtures that escape their boundary, or repository evidence packages.

## 8. Ownership and change protocol

A change touching a listed source root, contract, test, or primary document must update the canonical module record when ownership, interfaces, platform state, evidence ceiling, or external gates change. Run `python3 tools/generate_module_docs.py --check` and `python3 tools/validate_module_semantics.py`; obtain the applicable Code Owner review; run all seven canonical CI jobs on one unchanged head; and bind any promotion to fresh exact-head evidence. Administrator bypass, self-review, stale evidence reuse, or generated prose alone cannot approve the change.
