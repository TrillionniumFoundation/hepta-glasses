# `identity-control-plane` module engineering handoff

Canonical registry digest: `1b4152978fa8cd1778cb793cc3f91989647792ae23860654e803a0b9483dd522`

Owner: `cloud-security`

Lifecycle: `development_reference`

Profile: `engineering-handoff-v1`

This generated handoff is a module-specific navigation and consistency surface. It does not replace the owner-authored primary document `docs/development/DURABLE_IDENTITY.md` or manufacture deployment, physical-device, provider, signing, assurance, pilot, store, or release evidence.

## 1. Purpose and authority boundary

The module identifier is `identity-control-plane` and its accountable owner is `cloud-security`. Its current platform state is:

> Python provides SQLite durable identity, an authenticated signing-broker client, unified model/speech/mutation principals and a durable mutation-lease authority; Flutter consumes account token providers through fail-closed registries.

Implementation authority is limited to the source roots listed below. Anything outside those roots requires an explicit registry change and owner review. External gates remain non-source authorities and are never inferred from a green repository test.

### Source roots

- `services/control_plane/identity.py`
- `services/control_plane/__init__.py`
- `services/control_plane/durable_state.py`
- `services/control_plane/durable_identity.py`
- `services/control_plane/identity_authority.py`
- `services/control_plane/authenticated_principals.py`
- `services/control_plane/mutation_authority.py`
- `services/control_plane/account_runtime.py`

## 2. Public interfaces and contracts

The primary engineering description is `docs/development/DURABLE_IDENTITY.md`. The following contracts are the machine-readable interface and compatibility boundary for this module:

- `contracts/control-plane-v1.json`
- `schemas/access-token-claims.schema.json`
- `contracts/realtime-speech-custody-v2.json`
- `contracts/identity-authority-v1.json`
- `contracts/hg0087-production-v1.json`

The following documentation forms the reviewed human interface. A contract, schema, command, channel, API, storage layout, or externally visible behavior change must update every affected reference in the same candidate:

- `docs/MODULE_DEVELOPMENT_GUIDE.md#identity-control-plane`
- `docs/operations/PRODUCTION_CONTROL_PLANE_RUNBOOK.md`
- `docs/development/MODULE_HANDOFF.md#identity-control-plane`
- `docs/development/HG0087_PRODUCTION_IMPLEMENTATION.md`
- `docs/operations/HG0087_PRODUCTION_RUNTIME_RUNBOOK.md`
- `docs/development/DURABLE_IDENTITY.md`
- `docs/operations/IDENTITY_AUTHORITY_RUNBOOK.md`
- `docs/development/IDENTITY_ENROLLMENT_FRESHNESS.md`
- `docs/development/AUTHENTICATED_PRINCIPALS.md`
- `docs/development/MUTATION_AUTHORITY.md`

## 3. State, concurrency, and cancellation

State ownership, concurrency, cancellation, generation fencing, idempotency, and late-result behavior are defined jointly by the primary document, the registered source roots, and the contracts above. A change is inadmissible when those surfaces disagree. Unknown state, stale generation, expired authority, ambiguous ownership, or cancellation races must fail closed rather than silently commit a side effect.

## 4. Failure, recovery, and idempotency

The module must preserve explicit pre-effect failure, indeterminate-after-possible-effect, authoritative readback, retry, replay, and recovery semantics documented by its contracts. Recovery must not widen authority, restore revoked state, reuse a conflicting idempotency key, or convert missing evidence into success. Cross-module recovery changes require review from every affected owner.

## 5. Configuration, compatibility, and migration

Configuration and migration are source objects. Dependency, toolchain, schema, provider, platform, package identity, storage, policy, or firmware movement requires compatibility analysis and fresh qualification for the affected evidence axes. No historical Artifact, approval, physical report, provider receipt, signature, or release decision automatically transfers to a successor.

## 6. Operations, tests, observability, and SLO

The registered executable verification surfaces are:

- `services/control_plane/test_identity.py`
- `services/control_plane/test_durable_identity.py`
- `services/control_plane/test_identity_authority.py`
- `services/control_plane/test_identity_enrollment_freshness.py`
- `services/control_plane/test_authenticated_principals.py`
- `services/control_plane/test_mutation_authority.py`
- `services/control_plane/test_account_runtime.py`

Tests prove only their declared environment and assertions. Operational acceptance additionally requires bounded logs, privacy-safe traces, stable error classes, relevant SLO measurements, rollback/recovery procedures, and exact candidate identity. Module owners must record negative-path evidence, not only successful examples.

## 7. Security, privacy, and evidence ceiling

The current evidence ceiling is:

> Source integration does not establish deployed KMS/HSM, Android/Apple attestation, lost-device recovery, durable downstream revoke delivery, active-pair service operation or independent acceptance.

The unresolved external or authority-owned boundaries are:

- persistent database, KMS/HSM, platform attestation, multi-instance revocation and recovery drills

Secrets, raw credentials, signing material, unrestricted mutation authority, and sensitive user content must not be introduced into source, prompts, ordinary logs, generated documentation, test fixtures that escape their boundary, or repository evidence packages.

## 8. Ownership and change protocol

A change touching a listed source root, contract, test, or primary document must update the canonical module record when ownership, interfaces, platform state, evidence ceiling, or external gates change. Run `python3 tools/generate_module_docs.py --check` and `python3 tools/validate_module_semantics.py`; obtain the applicable Code Owner review; run all seven canonical CI jobs on one unchanged head; and bind any promotion to fresh exact-head evidence. Administrator bypass, self-review, stale evidence reuse, or generated prose alone cannot approve the change.
