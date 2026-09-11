# `assistant-speech` module engineering handoff

Canonical registry digest: `c05e8bdc7cf79b6f7cd0c1808b6d8d3ba8f7a545e5be09d6a1fc15641bef04af`

Owner: `mobile-ai`

Lifecycle: `source_candidate`

Profile: `engineering-handoff-v1`

This generated handoff is a module-specific navigation and consistency surface. It does not replace the owner-authored primary document `docs/MODULE_DEVELOPMENT_GUIDE.md#assistant-speech` or manufacture deployment, physical-device, provider, signing, assurance, pilot, store, or release evidence.

## 1. Purpose and authority boundary

The module identifier is `assistant-speech` and its accountable owner is `mobile-ai`. Its current platform state is:

> iOS uses system speech when permission, locale and device support are present. Android consumes right-leg G1 LC3 frames through a bounded, ticket-bound PCM-to-ASR session whose bootstrap and final response are bound to assistant generation, BLE generation and pair identity.

Implementation authority is limited to the source roots listed below. Anything outside those roots requires an explicit registry change and owner review. External gates remain non-source authorities and are never inferred from a green repository test.

### Source roots

- `lib/services/evenai.dart`
- `lib/runtime/assistant_session.dart`
- `lib/runtime/model_gateway.dart`
- `lib/services/api_services.dart`
- `lib/services/api_services_deepseek.dart`
- `ios/Runner/SpeechStreamRecognizer.swift`
- `services/model_gateway/speech.py`
- `services/model_gateway/speech_ingress.py`

## 2. Public interfaces and contracts

The primary engineering description is `docs/MODULE_DEVELOPMENT_GUIDE.md#assistant-speech`. The following contracts are the machine-readable interface and compatibility boundary for this module:

- `schemas/realtime-ticket.schema.json`
- `schemas/display-card.schema.json`

The following documentation forms the reviewed human interface. A contract, schema, command, channel, API, storage layout, or externally visible behavior change must update every affected reference in the same candidate:

- `docs/MODULE_DEVELOPMENT_GUIDE.md#assistant-speech`
- `docs/development/MODULE_HANDOFF.md#assistant-speech`
- `docs/development/SPEECH_BOOTSTRAP_CUSTODY.md`
- `docs/operations/SPEECH_BOOTSTRAP_RUNBOOK.md`
- `docs/development/AUTHENTICATED_PRINCIPALS.md`

## 3. State, concurrency, and cancellation

State ownership, concurrency, cancellation, generation fencing, idempotency, and late-result behavior are defined jointly by the primary document, the registered source roots, and the contracts above. A change is inadmissible when those surfaces disagree. Unknown state, stale generation, expired authority, ambiguous ownership, or cancellation races must fail closed rather than silently commit a side effect.

## 4. Failure, recovery, and idempotency

The module must preserve explicit pre-effect failure, indeterminate-after-possible-effect, authoritative readback, retry, replay, and recovery semantics documented by its contracts. Recovery must not widen authority, restore revoked state, reuse a conflicting idempotency key, or convert missing evidence into success. Cross-module recovery changes require review from every affected owner.

## 5. Configuration, compatibility, and migration

Configuration and migration are source objects. Dependency, toolchain, schema, provider, platform, package identity, storage, policy, or firmware movement requires compatibility analysis and fresh qualification for the affected evidence axes. No historical Artifact, approval, physical report, provider receipt, signature, or release decision automatically transfers to a successor.

## 6. Operations, tests, observability, and SLO

The registered executable verification surfaces are:

- `test/runtime/assistant_session_test.dart`
- `test/runtime/model_gateway_test.dart`
- `test/runtime/ios_speech_finalization_contract_test.dart`
- `test/runtime/microphone_retry_contract_test.dart`
- `services/model_gateway/test_speech_custody.py`
- `services/model_gateway/test_speech_ingress.py`

Tests prove only their declared environment and assertions. Operational acceptance additionally requires bounded logs, privacy-safe traces, stable error classes, relevant SLO measurements, rollback/recovery procedures, and exact candidate identity. Module owners must record negative-path evidence, not only successful examples.

## 7. Security, privacy, and evidence ceiling

The current evidence ceiling is:

> Source integration does not establish live speech tenancy, production identity/token delivery, retention/revocation operations or physical latency/accuracy/privacy qualification.

The unresolved external or authority-owned boundaries are:

- Android PCM-to-ASR, production model/realtime tenancy and physical latency/privacy qualification

Secrets, raw credentials, signing material, unrestricted mutation authority, and sensitive user content must not be introduced into source, prompts, ordinary logs, generated documentation, test fixtures that escape their boundary, or repository evidence packages.

## 8. Ownership and change protocol

A change touching a listed source root, contract, test, or primary document must update the canonical module record when ownership, interfaces, platform state, evidence ceiling, or external gates change. Run `python3 tools/generate_module_docs.py --check` and `python3 tools/validate_module_semantics.py`; obtain the applicable Code Owner review; run all seven canonical CI jobs on one unchanged head; and bind any promotion to fresh exact-head evidence. Administrator bypass, self-review, stale evidence reuse, or generated prose alone cannot approve the change.
