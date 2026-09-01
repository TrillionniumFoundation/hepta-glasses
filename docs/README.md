# Hepta Glasses documentation index

## Canonical current truth

1. `HEPTA_GLASSES_CANONICAL_DEVELOPMENT_PLAN.md` — normative G0–G8 sequence, invariants, gates, and evidence levels.
2. `CURRENT_STATE.md` — demonstrated source state, current evidence ceiling, and explicit non-claims.
3. `PROJECT_STATE.json` — machine-readable source authority, dynamic gate, and external-blocker contract.
4. `PRODUCT_BOUNDARY.md` — device, edge, cloud, capability, model, Codex, legacy-exclusion, and release boundaries.
5. `ARCHITECTURE.md` — data flow and authority topology.
6. `MODULES.json` — machine-readable module ownership, source, documentation, test, contract, lifecycle, and external-gate registry.
7. `MODULE_DEVELOPMENT_GUIDE.md` — detailed technical development guide for every registered module.
8. `CAPABILITY_MODEL.md` — risk tiers, exact leases, and mutation admission.
9. `PLATFORM_CAPABILITIES.json` — source capability and physical-attestation matrix.
10. `THREAT_MODEL.md` — trust boundaries and fail-closed controls.
11. `PRIVACY_MODEL.md` — data classes, retention defaults, consent, export, and deletion.
12. `GAP_LEDGER.yaml` — v6 machine-readable source closures and external/admin/upstream gates.
13. `EVIDENCE_INDEX.yaml` — source, CI, device, governance, review, pilot, and release evidence registry.

A later plan or ADR must state what it supersedes and update Current State, Product Boundary, Module Registry, Module Guide, Gap Ledger, Evidence Index, and affected machine contracts in the same change.

## Device and mobile development

- `G1_BLE_CONNECTION.md` — detailed Chinese G1 dual-BLE protocol, callback authority, idempotency, quarantine, platform readiness, commands, and tests.
- `G1_BLE_CONNECTION.en.md` — English G1 source specification.
- `MODULE_DEVELOPMENT_GUIDE.md#mobile-shell` — mobile startup, UI, state, and fail-closed composition.
- `MODULE_DEVELOPMENT_GUIDE.md#edge-runtime` — runtime orchestration and effect scopes.
- `MODULE_DEVELOPMENT_GUIDE.md#policy-tool-gateway` — policy, leases, idempotency, audit, recovery, and reconciliation.
- `MODULE_DEVELOPMENT_GUIDE.md#audit-journal` — authenticated checkpoint and append semantics.
- `MODULE_DEVELOPMENT_GUIDE.md#g1-protocol-features` — text, assistant, bitmap, notification, microphone, heartbeat, and exit effects.
- `MODULE_DEVELOPMENT_GUIDE.md#assistant-speech` — speech finalization, model client, cancellation, paging, and privacy.
- `MODULE_DEVELOPMENT_GUIDE.md#android-native` — Android GATT, native processing, Keystore, build, and tests.
- `MODULE_DEVELOPMENT_GUIDE.md#ios-native` — iOS callback tokens, speech, Keychain/CryptoKit, build, and tests.
- `MODULE_DEVELOPMENT_GUIDE.md#digital-twin` — deterministic transport fault model and evidence ceiling.

## Service and specialist development

- `MODULE_DEVELOPMENT_GUIDE.md#model-gateway-service`
- `MODULE_DEVELOPMENT_GUIDE.md#identity-control-plane`
- `MODULE_DEVELOPMENT_GUIDE.md#realtime-control-plane`
- `MODULE_DEVELOPMENT_GUIDE.md#capability-control-plane`
- `MODULE_DEVELOPMENT_GUIDE.md#skills-registry`
- `MODULE_DEVELOPMENT_GUIDE.md#memory`
- `MODULE_DEVELOPMENT_GUIDE.md#codex-worker`
- `MODULE_DEVELOPMENT_GUIDE.md#mcp-adapter`
- `services/model_gateway/README.md`
- `services/codex_worker/README.md`
- `adapters/mcp/README.md`

## Qualification, compatibility, and governance development

- `MODULE_DEVELOPMENT_GUIDE.md#qualification-release`
- `MODULE_DEVELOPMENT_GUIDE.md#contracts-compatibility`
- `MODULE_DEVELOPMENT_GUIDE.md#repository-governance`
- `MODULE_DEVELOPMENT_GUIDE.md#native-dependencies`
- `development/G8_METADATA_AND_DOCUMENTATION_CLOSURE.md`
- `development/G8_SOURCE_REMEDIATION.md`
- `development/G7_SOURCE_CONVERGENCE.md`
- `development/G5_AUDIT_CLOSURE.md`
- `development/G4_SOURCE_CLOSURE.md`
- `development/G3_G8_SOURCE_CLOSURE.md`
- `evidence/2026-08-30-foundation-source-closure.md`

## Operations

- `operations/PRODUCTION_CONTROL_PLANE_RUNBOOK.md`
- `operations/REALTIME_AND_CAPABILITY_RUNBOOK.md`
- `operations/DEVICE_QUALIFICATION_RUNBOOK.md`
- `operations/REPOSITORY_GOVERNANCE_RUNBOOK.md`
- `operations/PRIVACY_SECURITY_REVIEW_CHECKLIST.md`
- `operations/RELEASE_AND_ROLLBACK_RUNBOOK.md`
- `operations/CREDENTIAL_INCIDENT_RUNBOOK.md`

## Architecture decisions

- `adr/ADR-0001-distributed-os-boundary.md`
- `adr/ADR-0002-codex-authority-boundary.md`
- `adr/ADR-0003-edge-runtime-language.md`

## Composed machine contracts

- `../contracts/hepta-glasses-runtime-v1.json` — edge runtime composition and invariant set.
- `../contracts/control-plane-v1.json` — identity, realtime, capability, Skills, and Memory control-plane composition.
- `../contracts/g1-ble-protocol-v1.json` — dual-BLE UUID, readiness, framing, command, callback, authority, and uncertainty contract.
- `../contracts/main-branch-protection-v1.json` — canonical protected-main policy.
- `../contracts/qualification-slo-v1.json` — physical qualification thresholds and required trace semantics.
- `../contracts/release-gates-v1.json` — source and product evidence requirements.
- `../contracts/history-scan-acknowledgements-v1.json` — bounded, redacted history-scan acknowledgement contract.

## JSON Schemas

`../schemas/` contains Draft 2020-12 schemas for access-token claims, agent intents, decision leases, device qualification reports, display cards, glasses events, memory records, realtime tickets, release evidence bundles, Skill manifests, tool requests, and tool receipts. `tools/validate_repository.py` validates the schema shape; `tools/validate_repository_metadata.py` validates that every module and gap references existing source, documents, tests, and contracts.
