# `external-evidence-authentication` module engineering handoff

Canonical registry digest: `1724c910f392ab2cc88922962b0088c9102f128b5de7e4a5062185a4dd610d56`

Owner: `release-security`

Lifecycle: `source_candidate`

Profile: `engineering-handoff-v1`

This generated handoff is a module-specific navigation and consistency surface. It does not replace the owner-authored primary document `docs/development/G9_TERMINAL_EXTERNAL_CLOSURE.md` or manufacture deployment, physical-device, provider, signing, assurance, pilot, store, or release evidence.

## 1. Purpose and authority boundary

The module identifier is `external-evidence-authentication` and its accountable owner is `release-security`. Its current platform state is:

> Python trusted verifier on a controlled POSIX host.

Implementation authority is limited to the source roots listed below. Anything outside those roots requires an explicit registry change and owner review. External gates remain non-source authorities and are never inferred from a green repository test.

### Source roots

- `tools/external_evidence`
- `tools/external_evidence/snapshot_io.py`
- `tools/external_evidence/signing_io.py`
- `tools/external_evidence/signing.py`
- `tools/validate_external_evidence.py`
- `tools/sign_external_evidence.py`
- `evidence/external`
- `evidence/templates/external-evidence-bundle.template.json`
- `evidence/templates/external-authority-trust-registry.template.json`

## 2. Public interfaces and contracts

The primary engineering description is `docs/development/G9_TERMINAL_EXTERNAL_CLOSURE.md`. The following contracts are the machine-readable interface and compatibility boundary for this module:

- `contracts/external-evidence-envelope-v1.json`
- `schemas/external-evidence-envelope.schema.json`
- `schemas/external-authority-trust-registry.schema.json`

The following documentation forms the reviewed human interface. A contract, schema, command, channel, API, storage layout, or externally visible behavior change must update every affected reference in the same candidate:

- `docs/development/G9_TERMINAL_EXTERNAL_CLOSURE.md`
- `docs/development/G9_FILESYSTEM_CUSTODY_HARDENING.md`
- `docs/adr/ADR-0004-external-evidence-authentication.md`
- `docs/adr/ADR-0006-external-evidence-filesystem-custody.md`
- `docs/adr/ADR-0007-evidence-object-identity-and-bounded-custody.md`
- `evidence/external/README.md`
- `docs/development/MODULE_HANDOFF.md#external-evidence-authentication`

## 3. State, concurrency, and cancellation

State ownership, concurrency, cancellation, generation fencing, idempotency, and late-result behavior are defined jointly by the primary document, the registered source roots, and the contracts above. A change is inadmissible when those surfaces disagree. Unknown state, stale generation, expired authority, ambiguous ownership, or cancellation races must fail closed rather than silently commit a side effect.

## 4. Failure, recovery, and idempotency

The module must preserve explicit pre-effect failure, indeterminate-after-possible-effect, authoritative readback, retry, replay, and recovery semantics documented by its contracts. Recovery must not widen authority, restore revoked state, reuse a conflicting idempotency key, or convert missing evidence into success. Cross-module recovery changes require review from every affected owner.

## 5. Configuration, compatibility, and migration

Configuration and migration are source objects. Dependency, toolchain, schema, provider, platform, package identity, storage, policy, or firmware movement requires compatibility analysis and fresh qualification for the affected evidence axes. No historical Artifact, approval, physical report, provider receipt, signature, or release decision automatically transfers to a successor.

## 6. Operations, tests, observability, and SLO

The registered executable verification surfaces are:

- `services/qualification/external_evidence_test_support.py`
- `services/qualification/test_external_evidence.py`
- `services/qualification/test_external_evidence_adversarial.py`
- `services/qualification/test_external_evidence_json_safety.py`
- `services/qualification/test_external_evidence_key_alias.py`
- `services/qualification/test_external_evidence_key_type.py`
- `services/qualification/test_external_evidence_repository.py`
- `services/qualification/test_external_evidence_review_order.py`
- `services/qualification/test_external_evidence_scoped_snapshot.py`
- `services/qualification/test_external_evidence_filesystem_hardening.py`
- `services/qualification/test_external_evidence_signature_time.py`
- `services/qualification/test_external_evidence_signing.py`
- `services/qualification/test_external_evidence_signer_custody.py`
- `services/qualification/test_external_evidence_signing_boundaries.py`
- `services/qualification/test_external_evidence_snapshot.py`
- `services/qualification/test_g9_metadata.py`

Tests prove only their declared environment and assertions. Operational acceptance additionally requires bounded logs, privacy-safe traces, stable error classes, relevant SLO measurements, rollback/recovery procedures, and exact candidate identity. Module owners must record negative-path evidence, not only successful examples.

## 7. Security, privacy, and evidence ceiling

The current evidence ceiling is:

> The repository cannot create real issuer authority, out-of-band pin administration, independent acceptance or the facts described by external evidence.

The unresolved external or authority-owned boundaries are:

- out-of-band trust-registry administration and digest distribution
- proof of possession and authority for every enrolled issuer and reviewer key
- real physical, provider, administrator, vendor, assurance, signing, pilot and store evidence

Secrets, raw credentials, signing material, unrestricted mutation authority, and sensitive user content must not be introduced into source, prompts, ordinary logs, generated documentation, test fixtures that escape their boundary, or repository evidence packages.

## 8. Ownership and change protocol

A change touching a listed source root, contract, test, or primary document must update the canonical module record when ownership, interfaces, platform state, evidence ceiling, or external gates change. Run `python3 tools/generate_module_docs.py --check` and `python3 tools/validate_module_semantics.py`; obtain the applicable Code Owner review; run all seven canonical CI jobs on one unchanged head; and bind any promotion to fresh exact-head evidence. Administrator bypass, self-review, stale evidence reuse, or generated prose alone cannot approve the change.
