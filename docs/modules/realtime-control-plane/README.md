# `realtime-control-plane` module engineering handoff

Canonical registry digest: `bbf23c8764312c30e116e2812eda13abc06ab80b38f950ea2cdf0aa1f2b25eaf`

Owner: `cloud`

Lifecycle: `development_reference`

Profile: `engineering-handoff-v1`

This generated handoff is a module-specific navigation and consistency surface. It does not replace the owner-authored primary document `docs/development/REALTIME_ADMISSION.md` or manufacture deployment, physical-device, provider, signing, assurance, pilot, store, or release evidence.

## 1. Purpose and authority boundary

The module identifier is `realtime-control-plane` and its accountable owner is `cloud`. Its current platform state is:

> Python reference APIs plus SQLite realtime custody with an explicit trusted host clock, final admission-expiry checks and durable cleanup of expired activation results.

Implementation authority is limited to the source roots listed below. Anything outside those roots requires an explicit registry change and owner review. External gates remain non-source authorities and are never inferred from a green repository test.

### Source roots

- `services/control_plane/realtime.py`
- `services/control_plane/durable_realtime.py`
- `services/control_plane/realtime_recovery.py`
- `services/control_plane/realtime_provider_binding.py`

## 2. Public interfaces and contracts

The primary engineering description is `docs/development/REALTIME_ADMISSION.md`. The following contracts are the machine-readable interface and compatibility boundary for this module:

- `contracts/control-plane-v1.json`
- `schemas/realtime-ticket.schema.json`
- `contracts/realtime-speech-custody-v2.json`
- `contracts/realtime-admission-v1.json`

The following documentation forms the reviewed human interface. A contract, schema, command, channel, API, storage layout, or externally visible behavior change must update every affected reference in the same candidate:

- `docs/MODULE_DEVELOPMENT_GUIDE.md#realtime-control-plane`
- `docs/operations/REALTIME_AND_CAPABILITY_RUNBOOK.md`
- `docs/development/MODULE_HANDOFF.md#realtime-control-plane`
- `docs/development/HG0087_PRODUCTION_IMPLEMENTATION.md`
- `docs/operations/HG0087_PRODUCTION_RUNTIME_RUNBOOK.md`
- `docs/development/REALTIME_ADMISSION.md`
- `docs/operations/REALTIME_ADMISSION_RUNBOOK.md`
- `docs/development/REALTIME_PROVIDER_BINDING.md`

## 3. State, concurrency, and cancellation

State ownership, concurrency, cancellation, generation fencing, idempotency, and late-result behavior are defined jointly by the primary document, the registered source roots, and the contracts above. A change is inadmissible when those surfaces disagree. Unknown state, stale generation, expired authority, ambiguous ownership, or cancellation races must fail closed rather than silently commit a side effect.

## 4. Failure, recovery, and idempotency

The module must preserve explicit pre-effect failure, indeterminate-after-possible-effect, authoritative readback, retry, replay, and recovery semantics documented by its contracts. Recovery must not widen authority, restore revoked state, reuse a conflicting idempotency key, or convert missing evidence into success. Cross-module recovery changes require review from every affected owner.

## 5. Configuration, compatibility, and migration

Configuration and migration are source objects. Dependency, toolchain, schema, provider, platform, package identity, storage, policy, or firmware movement requires compatibility analysis and fresh qualification for the affected evidence axes. No historical Artifact, approval, physical report, provider receipt, signature, or release decision automatically transfers to a successor.

## 6. Operations, tests, observability, and SLO

The registered executable verification surfaces are:

- `services/control_plane/test_realtime.py`
- `services/control_plane/test_durable_realtime.py`
- `services/control_plane/test_realtime_custody.py`
- `services/control_plane/test_realtime_admission.py`
- `services/control_plane/test_realtime_recovery_budget.py`
- `services/control_plane/test_realtime_result_custody.py`
- `services/control_plane/test_realtime_provider_binding.py`

Tests prove only their declared environment and assertions. Operational acceptance additionally requires bounded logs, privacy-safe traces, stable error classes, relevant SLO measurements, rollback/recovery procedures, and exact candidate identity. Module owners must record negative-path evidence, not only successful examples.

## 7. Security, privacy, and evidence ceiling

The current evidence ceiling is:

> Local custody and deadline tests do not establish live provider exchange, authenticated ingress, session-lifetime enforcement, remote cleanup facts, anti-rollback or production latency.

The unresolved external or authority-owned boundaries are:

- production realtime provider, OAuth registration, broker persistence and provider-side revoke

Secrets, raw credentials, signing material, unrestricted mutation authority, and sensitive user content must not be introduced into source, prompts, ordinary logs, generated documentation, test fixtures that escape their boundary, or repository evidence packages.

## 8. Ownership and change protocol

A change touching a listed source root, contract, test, or primary document must update the canonical module record when ownership, interfaces, platform state, evidence ceiling, or external gates change. Run `python3 tools/generate_module_docs.py --check` and `python3 tools/validate_module_semantics.py`; obtain the applicable Code Owner review; run all seven canonical CI jobs on one unchanged head; and bind any promotion to fresh exact-head evidence. Administrator bypass, self-review, stale evidence reuse, or generated prose alone cannot approve the change.
