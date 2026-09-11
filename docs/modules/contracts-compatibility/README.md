# `contracts-compatibility` module engineering handoff

Canonical registry digest: `acc6449a06d6843ac3ede4f9efd8e40d4910af09838b4b1ba3937c7acfe2c3e8`

Owner: `architecture`

Lifecycle: `source_candidate`

Profile: `engineering-handoff-v1`

This generated handoff is a module-specific navigation and consistency surface. It does not replace the owner-authored primary document `docs/MODULE_DEVELOPMENT_GUIDE.md#contracts-compatibility` or manufacture deployment, physical-device, provider, signing, assurance, pilot, store, or release evidence.

## 1. Purpose and authority boundary

The module identifier is `contracts-compatibility` and its accountable owner is `architecture`. Its current platform state is:

> Contracts span Dart/Python and native adapters; vector coverage does not imply deployed consumer compatibility.

Implementation authority is limited to the source roots listed below. Anything outside those roots requires an explicit registry change and owner review. External gates remain non-source authorities and are never inferred from a green repository test.

### Source roots

- `contracts`
- `schemas`
- `contracts/conformance`
- `services/qualification/cross_language_json_reference.py`
- `services/qualification/g1_packet_reference.py`

## 2. Public interfaces and contracts

The primary engineering description is `docs/MODULE_DEVELOPMENT_GUIDE.md#contracts-compatibility`. The following contracts are the machine-readable interface and compatibility boundary for this module:

- `contracts/hepta-glasses-runtime-v1.json`
- `contracts/control-plane-v1.json`
- `contracts/g1-ble-protocol-v1.json`
- `contracts/release-gates-v1.json`
- `contracts/conformance/canonical-json-v1.json`
- `contracts/conformance/g1-packet-v1.json`
- `contracts/conformance/mutation-authority-v1.json`
- `contracts/release-versioning-v1.json`
- `schemas/source-artifact-archive-receipt.schema.json`

The following documentation forms the reviewed human interface. A contract, schema, command, channel, API, storage layout, or externally visible behavior change must update every affected reference in the same candidate:

- `docs/MODULE_DEVELOPMENT_GUIDE.md#contracts-compatibility`
- `docs/development/MODULE_HANDOFF.md#contracts-compatibility`
- `docs/development/CRITICAL_TEST_DEPTH.md`
- `docs/development/RELEASE_VERSIONING.md`
- `docs/development/SOURCE_ARTIFACT_ARCHIVAL.md`

## 3. State, concurrency, and cancellation

State ownership, concurrency, cancellation, generation fencing, idempotency, and late-result behavior are defined jointly by the primary document, the registered source roots, and the contracts above. A change is inadmissible when those surfaces disagree. Unknown state, stale generation, expired authority, ambiguous ownership, or cancellation races must fail closed rather than silently commit a side effect.

## 4. Failure, recovery, and idempotency

The module must preserve explicit pre-effect failure, indeterminate-after-possible-effect, authoritative readback, retry, replay, and recovery semantics documented by its contracts. Recovery must not widen authority, restore revoked state, reuse a conflicting idempotency key, or convert missing evidence into success. Cross-module recovery changes require review from every affected owner.

## 5. Configuration, compatibility, and migration

Configuration and migration are source objects. Dependency, toolchain, schema, provider, platform, package identity, storage, policy, or firmware movement requires compatibility analysis and fresh qualification for the affected evidence axes. No historical Artifact, approval, physical report, provider receipt, signature, or release decision automatically transfers to a successor.

## 6. Operations, tests, observability, and SLO

The registered executable verification surfaces are:

- `tools/validate_repository.py`
- `tools/validate_repository_metadata.py`
- `services/qualification/test_cross_language_conformance.py`
- `test/runtime/canonical_json_conformance_test.dart`
- `services/qualification/test_mutation_authority_conformance.py`
- `services/qualification/test_release_version.py`
- `services/qualification/test_source_artifact_archive_receipt.py`

Tests prove only their declared environment and assertions. Operational acceptance additionally requires bounded logs, privacy-safe traces, stable error classes, relevant SLO measurements, rollback/recovery procedures, and exact candidate identity. Module owners must record negative-path evidence, not only successful examples.

## 7. Security, privacy, and evidence ceiling

The current evidence ceiling is:

> Source conformance is not production rollout, backward compatibility telemetry or provider/vendor certification.

The unresolved external or authority-owned boundaries are:

- consumer/provider compatibility evidence when contracts are deployed across independently versioned services

Secrets, raw credentials, signing material, unrestricted mutation authority, and sensitive user content must not be introduced into source, prompts, ordinary logs, generated documentation, test fixtures that escape their boundary, or repository evidence packages.

## 8. Ownership and change protocol

A change touching a listed source root, contract, test, or primary document must update the canonical module record when ownership, interfaces, platform state, evidence ceiling, or external gates change. Run `python3 tools/generate_module_docs.py --check` and `python3 tools/validate_module_semantics.py`; obtain the applicable Code Owner review; run all seven canonical CI jobs on one unchanged head; and bind any promotion to fresh exact-head evidence. Administrator bypass, self-review, stale evidence reuse, or generated prose alone cannot approve the change.
