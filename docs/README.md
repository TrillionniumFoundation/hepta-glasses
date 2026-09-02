# Hepta Glasses documentation index

## Canonical current truth

1. `HEPTA_GLASSES_CANONICAL_DEVELOPMENT_PLAN.md` — normative G0–G8 source sequence, invariants, gates, and evidence levels.
2. `CURRENT_STATE.md` — demonstrated source state and explicit non-claims.
3. `PROJECT_STATE.json` — machine-readable authority, dynamic gate, and external-blocker contract.
4. `PRODUCT_BOUNDARY.md` — device, edge, cloud, capability, model, Codex, and release boundaries.
5. `ARCHITECTURE.md` — data flow and authority topology.
6. `CAPABILITY_MODEL.md` — risk tiers, exact leases, and mutation admission.
7. `PLATFORM_CAPABILITIES.json` — source capability and physical-attestation matrix.
8. `THREAT_MODEL.md` — trust boundaries and fail-closed controls.
9. `PRIVACY_MODEL.md` — data classes, retention defaults, consent, export, and deletion.
10. `GAP_LEDGER.yaml` — machine-readable source gaps and external gates.
11. `EVIDENCE_INDEX.yaml` — source, CI, device, governance, review, pilot, and release evidence registry.
12. `MODULES.json` — machine-readable module ownership and coverage registry.
13. `MODULE_DEVELOPMENT_GUIDE.md` — detailed technical development guide for every registered module.

## Development

- `development/G9_TERMINAL_EXTERNAL_CLOSURE.md` — authenticated execution package for the 12 authority-owned gaps; layered on G8 and not itself external evidence.
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

A later plan or ADR must state what it supersedes and update Current State, Gap Ledger, Evidence Index, and affected machine contracts in the same change.

## Machine contracts

- `../contracts/g1-ble-protocol-v1.json` — dual-BLE UUID, readiness, framing, command, and uncertainty contract.
- `../contracts/external-evidence-envelope-v1.json` — authenticated authority-owned evidence and acceptance contract.
- `../schemas/external-evidence-envelope.schema.json` — evidence envelope schema.
- `../schemas/external-authority-trust-registry.schema.json` — externally pinned Ed25519 authority registry schema.
