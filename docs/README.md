# Hepta Glasses documentation index

## Canonical current truth

1. `HEPTA_GLASSES_CANONICAL_DEVELOPMENT_PLAN.md` — normative G0–G8 source sequence, invariants, gates, and evidence levels.
2. `CURRENT_STATE.md` — demonstrated G8 source state and explicit non-claims.
3. `PROJECT_STATE.json` — machine-readable G8 source authority, dynamic gate, and external-blocker contract.
4. `PRODUCT_BOUNDARY.md` — device, edge, cloud, capability, model, Codex, and release boundaries.
5. `ARCHITECTURE.md` — data flow and authority topology.
6. `CAPABILITY_MODEL.md` — risk tiers, exact leases, and mutation admission.
7. `PLATFORM_CAPABILITIES.json` — source capability and physical-attestation matrix.
8. `THREAT_MODEL.md` — trust boundaries and fail-closed controls.
9. `PRIVACY_MODEL.md` — data classes, retention defaults, consent, export, and deletion.
10. `GAP_LEDGER.yaml` — G8 machine-readable source gaps and inherited external gates.
11. `EVIDENCE_INDEX.yaml` — G8 source, CI, device, governance, review, pilot, and release evidence registry.
12. `MODULES.json` — G8 machine-readable module ownership and coverage registry.
13. `MODULE_DEVELOPMENT_GUIDE.md` — detailed technical development guide for every G8 registered module.

## G9 layered machine truth

G9 is a stacked evidence-authentication and latest-head CI-custody layer. It does not rewrite the frozen G8 candidate. Its supplements are:

- `G9_STATE.json` — source authority, latest-head concurrency custody, claim ceiling, and inherited 12-gap set.
- `G9_MODULES.json` — source/document/test/contract ownership for external-evidence authentication and CI custody.
- `G9_GAP_LEDGER.json` — source closure records for `HG-0073`, `HG-0074`, and `HG-0075`.
- `development/G9_TERMINAL_EXTERNAL_CLOSURE.md` — execution package for the authority-owned gaps; not itself external evidence.
- `development/G9_FILESYSTEM_CUSTODY_HARDENING.md` — exact-object evidence custody implementation and reopen conditions.

`services/qualification/test_g9_metadata.py` verifies these supplements, the G8 inheritance boundary, filesystem custody, and the absence of private-key material. `services/qualification/test_ci_latest_head_custody.py` verifies stale-run cancellation and exact-source identity in all seven jobs. Dedicated suites exercise directory and file replacement, URI aliases, aggregate bounds, SPKI retargeting, private-key replacement, and immutable successor creation.

## G10 layered machine truth

G10 is a versioned strict complete-closure layer over G9. It does not promote any inherited product row. Its supplements are:

- `G10_STATE.json` — live source authority, zero-open repository state, active complete-closure policy, trusted verifier boundary, canonical contract-content binding, and unchanged inherited 12-gap set.
- `G10_MODULES.json` — ownership and source/document/test/contract coverage for quorum, claim scope, review-set integrity, runtime authority, contract semantic binding, and committed-package admission.
- `G10_GAP_LEDGER.json` — source closure records for:
  - `HG-0076`: every named issuer authority class must participate through a distinct key and identity/organization seat;
  - `HG-0077`: every accepted reviewer co-signs the same policy, ordered final roster, and acceptance context;
  - `HG-0078`: complete-closure semantics use the signed G10 contract revision, exact class-scoped claim partition, and one immutable validation entrypoint;
  - `HG-0079`: repository CI recursively discovers every committed accepted envelope by stable descriptor-backed canonical content, independent of filename or successor depth;
  - `HG-0080`: public validation owns the current clock and canonical OpenSSL command and rejects caller overrides; and
  - `HG-0081`: issuer, evidence-set, and reviewer signatures bind the canonical SHA-256 of the complete current contract object.
- `development/G10_AUTHORITY_QUORUM_AND_REVIEW_INTEGRITY.md` — quorum, claim partition, review roster, recursive admission, implementation sequence, hostile tests, and external boundary.
- `development/G10_TRUSTED_VERIFIER_AND_CONTRACT_BINDING.md` — public/test runtime separation, contract-content signature binding, failure semantics, tests, operations, and reopen conditions.

`services/qualification/test_g10_metadata.py` verifies the G10 policy profile, class-scope partition, machine truth, public entrypoints, trusted runtime boundary, contract semantic binding, and repository gate. `services/qualification/test_external_evidence_complete_closure.py` proves missing quorum, key-seat reuse, cross-scope claims, G9 semantic downgrade, review deletion/reordering, acceptance mutation, and wrong-policy manifests fail closed. `services/qualification/test_external_evidence_runtime_policy.py` proves public clock and cryptographic-executable injection fail. `services/qualification/test_external_evidence_contract_binding.py` proves same-revision contract mutation changes every authority preimage. `services/qualification/test_external_evidence_repository.py` proves accepted immutable successors cannot evade protected-pin validation through nesting, opaque filenames, symbolic links, or check/read replacement.

## Development

- `development/G10_AUTHORITY_QUORUM_AND_REVIEW_INTEGRITY.md`
- `development/G10_TRUSTED_VERIFIER_AND_CONTRACT_BINDING.md`
- `development/G9_TERMINAL_EXTERNAL_CLOSURE.md`
- `development/G9_FILESYSTEM_CUSTODY_HARDENING.md`
- `development/G8_PRODUCTION_AUTHORITY_CLOSURE.md`
- `development/G8_METADATA_AND_DOCUMENTATION_CLOSURE.md`
- `development/G8_SOURCE_REMEDIATION.md`
- `development/G7_SOURCE_CONVERGENCE.md`
- `development/G5_AUDIT_CLOSURE.md`
- `development/G4_SOURCE_CLOSURE.md`
- `development/G3_G8_SOURCE_CLOSURE.md`
- `G1_BLE_CONNECTION.md`
- `G1_BLE_CONNECTION.en.md`

## Operations

- `operations/PRODUCTION_CONTROL_PLANE_RUNBOOK.md`
- `operations/REALTIME_AND_CAPABILITY_RUNBOOK.md`
- `operations/DEVICE_QUALIFICATION_RUNBOOK.md`
- `operations/REPOSITORY_GOVERNANCE_RUNBOOK.md`
- `operations/PRIVACY_SECURITY_REVIEW_CHECKLIST.md`
- `operations/RELEASE_AND_ROLLBACK_RUNBOOK.md`
- `operations/CREDENTIAL_INCIDENT_RUNBOOK.md`
- `../evidence/external/README.md` — versioned evidence custody, immutable signing, all-class quorum, exact class-scoped claims, final review-set binding, trusted runtime validation, canonical contract binding, recursive committed-package admission, external trust pin, and validation procedure.

## Architecture decisions

- `adr/ADR-0001-distributed-os-boundary.md`
- `adr/ADR-0002-codex-authority-boundary.md`
- `adr/ADR-0003-edge-runtime-language.md`
- `adr/ADR-0004-external-evidence-authentication.md` — out-of-band trust pin, actual Ed25519 key binding, signed evidence/reviews, strict parsing, and authority separation.
- `adr/ADR-0005-latest-head-ci-concurrency.md` — pull-request/branch concurrency custody, stale-run cancellation, and exact-source verification.
- `adr/ADR-0006-external-evidence-filesystem-custody.md` — lexical-path snapshots, descriptor-stable bounded reads, symlink-retarget fencing, and exclusive detached signatures.
- `adr/ADR-0007-evidence-object-identity-and-bounded-custody.md` — ordinary-object identity, canonical URIs, aggregate snapshot bounds, pinned-key normalization, private-key custody, and immutable bundle successors.
- `adr/ADR-0008-authority-quorum-and-review-set-integrity.md` — versioned complete-closure policy, all-class quorum, exact claim partition, final roster/context manifests, canonical entrypoint, and recursive stable accepted-envelope admission.
- `adr/ADR-0009-trusted-verifier-and-contract-content-binding.md` — current-time runtime authority, fixed cryptographic command, private deterministic test hook, and canonical contract digest in authority signatures.

A later plan or ADR must state what it supersedes and update the applicable Current State, Gap Ledger, Evidence Index, module registry, validators, tests, and affected machine contracts in the same change.

## Machine contracts

- `../contracts/g1-ble-protocol-v1.json` — dual-BLE UUID, readiness, framing, command, and uncertainty contract.
- `../contracts/external-evidence-envelope-v1.json` — versioned authenticated authority-owned evidence and complete-closure contract.
- `../schemas/external-evidence-envelope.schema.json` — evidence envelope schema.
- `../schemas/external-authority-trust-registry.schema.json` — externally pinned Ed25519 authority registry schema.
