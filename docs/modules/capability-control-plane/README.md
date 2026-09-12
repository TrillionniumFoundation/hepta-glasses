# `capability-control-plane` module engineering handoff

Canonical registry digest: `86dbfe12a286b7d5b8bcd7d4cb2693a892b178a095280d2bfb3298eb96ccf7d6`

Owner: `capabilities`

Lifecycle: `development_reference`

Profile: `engineering-handoff-v1`

This generated handoff is a module-specific navigation and consistency surface. It does not replace the owner-authored primary document `docs/development/DURABLE_CAPABILITIES.md` or manufacture deployment, physical-device, provider, signing, assurance, pilot, store, or release evidence.

## 1. Purpose and authority boundary

The module identifier is `capability-control-plane` and its accountable owner is `capabilities`. Its current platform state is:

> Python reference APIs plus SQLite intent/lease/readback custody and a Google Calendar single-event HTTPS adapter with final pre-POST authority revalidation; no authenticated production ingress is connected.

Implementation authority is limited to the source roots listed below. Anything outside those roots requires an explicit registry change and owner review. External gates remain non-source authorities and are never inferred from a green repository test.

### Source roots

- `services/control_plane/capabilities.py`
- `services/control_plane/bounded_calls.py`
- `services/control_plane/durable_capabilities.py`
- `services/control_plane/google_calendar.py`
- `services/control_plane/capability_suspension.py`
- `services/control_plane/oauth_vault.py`
- `services/control_plane/capability_payload_store.py`

## 2. Public interfaces and contracts

The primary engineering description is `docs/development/DURABLE_CAPABILITIES.md`. The following contracts are the machine-readable interface and compatibility boundary for this module:

- `contracts/control-plane-v1.json`
- `schemas/decision-lease.schema.json`
- `schemas/tool-receipt.schema.json`
- `contracts/capability-reference-v2.json`
- `contracts/durable-capability-v1.json`
- `contracts/google-calendar-capability-v1.json`

The following documentation forms the reviewed human interface. A contract, schema, command, channel, API, storage layout, or externally visible behavior change must update every affected reference in the same candidate:

- `docs/MODULE_DEVELOPMENT_GUIDE.md#capability-control-plane`
- `docs/operations/REALTIME_AND_CAPABILITY_RUNBOOK.md`
- `docs/development/REFERENCE_RUNTIME_HARDENING.md`
- `docs/development/MODULE_HANDOFF.md#capability-control-plane`
- `docs/development/DURABLE_CAPABILITIES.md`
- `docs/operations/DURABLE_CAPABILITY_RUNBOOK.md`
- `docs/development/GOOGLE_CALENDAR_CAPABILITY.md`
- `docs/operations/GOOGLE_CALENDAR_CAPABILITY_RUNBOOK.md`
- `docs/development/CAPABILITY_REVOCATION_SAFETY.md`

## 3. State, concurrency, and cancellation

State ownership, concurrency, cancellation, generation fencing, idempotency, and late-result behavior are defined jointly by the primary document, the registered source roots, and the contracts above. A change is inadmissible when those surfaces disagree. Unknown state, stale generation, expired authority, ambiguous ownership, or cancellation races must fail closed rather than silently commit a side effect.

## 4. Failure, recovery, and idempotency

The module must preserve explicit pre-effect failure, indeterminate-after-possible-effect, authoritative readback, retry, replay, and recovery semantics documented by its contracts. Recovery must not widen authority, restore revoked state, reuse a conflicting idempotency key, or convert missing evidence into success. Cross-module recovery changes require review from every affected owner.

## 5. Configuration, compatibility, and migration

Configuration and migration are source objects. Dependency, toolchain, schema, provider, platform, package identity, storage, policy, or firmware movement requires compatibility analysis and fresh qualification for the affected evidence axes. No historical Artifact, approval, physical report, provider receipt, signature, or release decision automatically transfers to a successor.

## 6. Operations, tests, observability, and SLO

The registered executable verification surfaces are:

- `services/control_plane/test_capabilities.py`
- `services/control_plane/test_capability_boundaries.py`
- `services/control_plane/test_durable_capabilities.py`
- `services/control_plane/test_google_calendar.py`
- `services/control_plane/test_capability_schema_integrity.py`
- `services/control_plane/test_capability_suspension.py`
- `services/control_plane/test_oauth_vault.py`
- `services/control_plane/test_capability_payload_store.py`

Tests prove only their declared environment and assertions. Operational acceptance additionally requires bounded logs, privacy-safe traces, stable error classes, relevant SLO measurements, rollback/recovery procedures, and exact candidate identity. Module owners must record negative-path evidence, not only successful examples.

## 7. Security, privacy, and evidence ceiling

The current evidence ceiling is:

> Local source and wire tests do not establish an OAuth consent/refresh vault, live provider ownership, encrypted payload custody, process isolation, independent review or product qualification.

The unresolved external or authority-owned boundaries are:

- production OAuth adapters, opaque credential vault, authoritative receipts and timeout reconciliation

Secrets, raw credentials, signing material, unrestricted mutation authority, and sensitive user content must not be introduced into source, prompts, ordinary logs, generated documentation, test fixtures that escape their boundary, or repository evidence packages.

## 8. Ownership and change protocol

A change touching a listed source root, contract, test, or primary document must update the canonical module record when ownership, interfaces, platform state, evidence ceiling, or external gates change. Run `python3 tools/generate_module_docs.py --check` and `python3 tools/validate_module_semantics.py`; obtain the applicable Code Owner review; run all seven canonical CI jobs on one unchanged head; and bind any promotion to fresh exact-head evidence. Administrator bypass, self-review, stale evidence reuse, or generated prose alone cannot approve the change.
