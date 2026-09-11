# `memory` module engineering handoff

Canonical registry digest: `d762c9133055b2dff479c494e4586fa0963950b3f92eb560ed3cbb31de2b1cca`

Owner: `privacy`

Lifecycle: `development_reference`

Profile: `engineering-handoff-v1`

This generated handoff is a module-specific navigation and consistency surface. It does not replace the owner-authored primary document `docs/development/DURABLE_MEMORY.md` or manufacture deployment, physical-device, provider, signing, assurance, pilot, store, or release evidence.

## 1. Purpose and authority boundary

The module identifier is `memory` and its accountable owner is `privacy`. Its current platform state is:

> Python includes a SQLite ciphertext-only durable Memory store with an external per-subject cipher/key-provider interface; Flutter answer history remains a separate default-off process-memory feature.

Implementation authority is limited to the source roots listed below. Anything outside those roots requires an explicit registry change and owner review. External gates remain non-source authorities and are never inferred from a green repository test.

### Source roots

- `services/skills/memory.py`
- `lib/controllers/evenai_model_controller.dart`
- `services/skills/durable_memory.py`
- `services/skills/durable_memory_schema.py`
- `services/skills/memory_service.py`

## 2. Public interfaces and contracts

The primary engineering description is `docs/development/DURABLE_MEMORY.md`. The following contracts are the machine-readable interface and compatibility boundary for this module:

- `schemas/memory-record.schema.json`
- `contracts/durable-memory-v1.json`

The following documentation forms the reviewed human interface. A contract, schema, command, channel, API, storage layout, or externally visible behavior change must update every affected reference in the same candidate:

- `docs/MODULE_DEVELOPMENT_GUIDE.md#memory`
- `docs/PRIVACY_MODEL.md`
- `docs/development/REFERENCE_RUNTIME_HARDENING.md`
- `docs/development/MODULE_HANDOFF.md#memory`
- `docs/development/DURABLE_MEMORY.md`
- `docs/development/MEMORY_COMPONENT_IDENTITY.md`

## 3. State, concurrency, and cancellation

State ownership, concurrency, cancellation, generation fencing, idempotency, and late-result behavior are defined jointly by the primary document, the registered source roots, and the contracts above. A change is inadmissible when those surfaces disagree. Unknown state, stale generation, expired authority, ambiguous ownership, or cancellation races must fail closed rather than silently commit a side effect.

## 4. Failure, recovery, and idempotency

The module must preserve explicit pre-effect failure, indeterminate-after-possible-effect, authoritative readback, retry, replay, and recovery semantics documented by its contracts. Recovery must not widen authority, restore revoked state, reuse a conflicting idempotency key, or convert missing evidence into success. Cross-module recovery changes require review from every affected owner.

## 5. Configuration, compatibility, and migration

Configuration and migration are source objects. Dependency, toolchain, schema, provider, platform, package identity, storage, policy, or firmware movement requires compatibility analysis and fresh qualification for the affected evidence axes. No historical Artifact, approval, physical report, provider receipt, signature, or release decision automatically transfers to a successor.

## 6. Operations, tests, observability, and SLO

The registered executable verification surfaces are:

- `services/skills/test_memory.py`
- `test/runtime/even_ai_history_page_test.dart`
- `services/qualification/test_history_consent_contract.py`
- `services/skills/test_memory_boundaries.py`
- `services/skills/test_durable_memory.py`
- `services/skills/test_durable_memory_schema.py`
- `services/skills/test_durable_memory_component_identity.py`
- `services/skills/test_memory_service.py`

Tests prove only their declared environment and assertions. Operational acceptance additionally requires bounded logs, privacy-safe traces, stable error classes, relevant SLO measurements, rollback/recovery procedures, and exact candidate identity. Module owners must record negative-path evidence, not only successful examples.

## 7. Security, privacy, and evidence ceiling

The current evidence ceiling is:

> The repository fixture cipher is not a production key service; authenticated ingress, KMS/HSM-backed subject keys, backup anti-rollback, downstream deletion evidence and independent privacy qualification remain open.

The unresolved external or authority-owned boundaries are:

- encrypted persistent storage, deletion/backup drills, regional retention and independent privacy review

Secrets, raw credentials, signing material, unrestricted mutation authority, and sensitive user content must not be introduced into source, prompts, ordinary logs, generated documentation, test fixtures that escape their boundary, or repository evidence packages.

## 8. Ownership and change protocol

A change touching a listed source root, contract, test, or primary document must update the canonical module record when ownership, interfaces, platform state, evidence ceiling, or external gates change. Run `python3 tools/generate_module_docs.py --check` and `python3 tools/validate_module_semantics.py`; obtain the applicable Code Owner review; run all seven canonical CI jobs on one unchanged head; and bind any promotion to fresh exact-head evidence. Administrator bypass, self-review, stale evidence reuse, or generated prose alone cannot approve the change.
