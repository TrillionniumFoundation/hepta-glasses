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

G9 is a stacked evidence-authentication and latest-head CI-custody layer. It does not rewrite the frozen G8 candidate. Its machine-readable supplements are:

- `G9_STATE.json` — source authority rule, latest-head concurrency custody, claim ceiling, zero-open source status, and the inherited 12-gap set.
- `G9_MODULES.json` — ownership and source/document/test/contract coverage for the external-evidence authentication and latest-head CI-custody modules.
- `G9_GAP_LEDGER.json` — source closure records for `HG-0073` and `HG-0074`, plus the exact inherited authority-owned gap IDs.
- `development/G9_TERMINAL_EXTERNAL_CLOSURE.md` — authenticated execution package for the 12 authority-owned gaps; not itself external evidence.

`services/qualification/test_g9_metadata.py` verifies these supplements, their referenced paths, their synchronization with the G8 ledger and G9 contract, and the absence of private-key material in repository custody. `services/qualification/test_ci_latest_head_custody.py` independently verifies stale-run cancellation and exact-head identity checks in all seven jobs.

## Development

- `development/G9_TERMINAL_EXTERNAL_CLOSURE.md`
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
- `../evidence/external/README.md` — authenticated evidence custody, external trust pin, and validation procedure.

## Architecture decisions

- `adr/ADR-0001-distributed-os-boundary.md`
- `adr/ADR-0002-codex-authority-boundary.md`
- `adr/ADR-0003-edge-runtime-language.md`
- `adr/ADR-0004-external-evidence-authentication.md` — out-of-band trust pin, actual Ed25519 key binding, signed evidence/reviews, strict parsing and authority separation.
- `adr/ADR-0005-latest-head-ci-concurrency.md` — pull-request/branch concurrency custody, stale-run cancellation and independent exact-source verification.

A later plan or ADR must state what it supersedes and update the applicable Current State, Gap Ledger, Evidence Index, module registry, validators, tests and affected machine contracts in the same change.

## Machine contracts

- `../contracts/g1-ble-protocol-v1.json` — dual-BLE UUID, readiness, framing, command, and uncertainty contract.
- `../contracts/external-evidence-envelope-v1.json` — authenticated authority-owned evidence and acceptance contract.
- `../schemas/external-evidence-envelope.schema.json` — evidence envelope schema.
- `../schemas/external-authority-trust-registry.schema.json` — externally pinned Ed25519 authority registry schema.
