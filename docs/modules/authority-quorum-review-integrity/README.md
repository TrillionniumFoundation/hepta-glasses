# `authority-quorum-review-integrity` module engineering handoff

Canonical registry digest: `206fa65f21fc9fc212b2c5963989d31d4f3e98df07725f5afbb43b5d83f85d20`

Owner: `release-security`

Lifecycle: `source_candidate`

Profile: `engineering-handoff-v1`

This generated handoff is a module-specific navigation and consistency surface. It does not replace the owner-authored primary document `docs/development/G10_AUTHORITY_QUORUM_AND_REVIEW_INTEGRITY.md` or manufacture deployment, physical-device, provider, signing, assurance, pilot, store, or release evidence.

## 1. Purpose and authority boundary

The module identifier is `authority-quorum-review-integrity` and its accountable owner is `release-security`. Its current platform state is:

> Trusted POSIX verifier host with a controlled OS/runtime boundary.

Implementation authority is limited to the source roots listed below. Anything outside those roots requires an explicit registry change and owner review. External gates remain non-source authorities and are never inferred from a green repository test.

### Source roots

- `tools/external_evidence/complete_closure.py`
- `tools/external_evidence/authority_seat_policy.py`
- `tools/external_evidence/repository_admission.py`
- `tools/external_evidence/semantic_binding.py`
- `tools/external_evidence/runtime_policy.py`
- `tools/external_evidence/openssl_policy.py`
- `tools/external_evidence/lexical_scope_policy.py`
- `tools/external_evidence/signing_custody_policy.py`
- `tools/external_evidence/cli.py`
- `tools/external_evidence/__init__.py`
- `tools/validate_external_evidence.py`
- `tools/external_evidence/committed_snapshot.py`

## 2. Public interfaces and contracts

The primary engineering description is `docs/development/G10_AUTHORITY_QUORUM_AND_REVIEW_INTEGRITY.md`. The following contracts are the machine-readable interface and compatibility boundary for this module:

- `contracts/external-evidence-envelope-v1.json`
- `schemas/external-evidence-envelope.schema.json`
- `schemas/external-authority-trust-registry.schema.json`

The following documentation forms the reviewed human interface. A contract, schema, command, channel, API, storage layout, or externally visible behavior change must update every affected reference in the same candidate:

- `docs/development/G10_AUTHORITY_QUORUM_AND_REVIEW_INTEGRITY.md`
- `docs/development/G10_AUTHORITY_SEAT_AND_REPOSITORY_ADMISSION_HARDENING.md`
- `docs/development/G10_TRUSTED_VERIFIER_AND_CONTRACT_BINDING.md`
- `docs/development/G10_LEXICAL_VALIDATION_CUSTODY.md`
- `docs/development/G10_SIGNING_TRANSACTION_CUSTODY.md`
- `docs/adr/ADR-0008-authority-quorum-and-review-set-integrity.md`
- `docs/adr/ADR-0009-trusted-verifier-and-contract-content-binding.md`
- `docs/adr/ADR-0010-lexical-validation-custody.md`
- `evidence/external/README.md`
- `docs/development/MODULE_HANDOFF.md#authority-quorum-review-integrity`
- `docs/development/ADMISSION_CONTINUITY.md`

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
- `services/qualification/test_external_evidence_authority_seat_scope.py`
- `services/qualification/test_external_evidence_complete_closure.py`
- `services/qualification/test_external_evidence_contract_binding.py`
- `services/qualification/test_external_evidence_entrypoint_snapshot.py`
- `services/qualification/test_external_evidence_lexical_scope_policy.py`
- `services/qualification/test_external_evidence_runtime_policy.py`
- `services/qualification/test_external_evidence_signing_transaction.py`
- `services/qualification/test_external_evidence_review_order.py`
- `services/qualification/test_external_evidence_repository.py`
- `services/qualification/test_external_evidence_repository_admission.py`
- `services/qualification/test_g9_metadata.py`
- `services/qualification/test_g10_metadata.py`
- `services/qualification/test_committed_snapshot.py`
- `services/qualification/test_committed_snapshot_signed.py`

Tests prove only their declared environment and assertions. Operational acceptance additionally requires bounded logs, privacy-safe traces, stable error classes, relevant SLO measurements, rollback/recovery procedures, and exact candidate identity. Module owners must record negative-path evidence, not only successful examples.

## 7. Security, privacy, and evidence ceiling

The current evidence ceiling is:

> Closes repository validation semantics only; real authorities, reviewers, trusted-host operation and evidence facts remain independently controlled.

The unresolved external or authority-owned boundaries are:

- out-of-band trust-registry administration and digest distribution
- real authority participation for every required issuer class
- final reviewer roster selection and independent acceptance
- protected CI pin for every committed accepted envelope
- trusted verifier host, correct system clock, root-owned immutable /usr/bin/openssl and controlled operating-system runtime dependencies
- physical, provider, administrator, vendor, assurance, signing, pilot and store evidence

Secrets, raw credentials, signing material, unrestricted mutation authority, and sensitive user content must not be introduced into source, prompts, ordinary logs, generated documentation, test fixtures that escape their boundary, or repository evidence packages.

## 8. Ownership and change protocol

A change touching a listed source root, contract, test, or primary document must update the canonical module record when ownership, interfaces, platform state, evidence ceiling, or external gates change. Run `python3 tools/generate_module_docs.py --check` and `python3 tools/validate_module_semantics.py`; obtain the applicable Code Owner review; run all seven canonical CI jobs on one unchanged head; and bind any promotion to fresh exact-head evidence. Administrator bypass, self-review, stale evidence reuse, or generated prose alone cannot approve the change.
