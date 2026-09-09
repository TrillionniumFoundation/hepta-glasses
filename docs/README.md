# Hepta Glasses documentation index

## Canonical current truth

1. `CURRENT_STATE.md` — current source, governance, platform, and external-authority truth.
2. `PROJECT_STATE.json` — machine-readable authority, last-qualified source, required checks, and remaining gates.
3. `REMEDIATION_GAP_LEDGER.json` — active repository remediation state.
4. `HG0087_IMPLEMENTATION_STATUS.json` — seven source-closed production-reference slices and their remaining external requirements.
5. `MATURITY_MODEL.md` — ordered maturity vocabulary from design through released product.
6. `development/2026-09-08_PRODUCTIZATION_ROADMAP.md` — prioritized productization and blocker-closure route.
7. `HEPTA_GLASSES_CANONICAL_DEVELOPMENT_PLAN.md` — normative G0–G8 source sequence, invariants, gates, and evidence levels.
8. `PRODUCT_BOUNDARY.md` — device, edge, cloud, capability, model, Codex, firmware, and release boundaries.
9. `ARCHITECTURE.md` — data flow and authority topology.
10. `CAPABILITY_MODEL.md` — risk tiers, exact leases, and mutation admission.
11. `PLATFORM_CAPABILITIES.json` — source capability and physical-attestation matrix.
12. `THREAT_MODEL.md` — trust boundaries and fail-closed controls.
13. `PRIVACY_MODEL.md` — data classes, retention defaults, consent, export, and deletion.
14. `GAP_LEDGER.yaml` — G8 source gaps and inherited external gates.
15. `EVIDENCE_INDEX.yaml` — source, CI, device, governance, review, pilot, and release evidence registry.
16. `MODULES.json` — base machine-readable module ownership and coverage registry.
17. `MODULE_COVERAGE.json` — flattened tracked-source ownership registry.
18. `MODULE_HANDOFF.json` and `development/MODULE_HANDOFF.md` — primary technical handoff for all 26 flattened modules.
19. `MODULE_DEVELOPMENT_GUIDE.md` — base detailed technical development guide.

The live pull-request head and Git tree identify the active source object. A copied SHA in prose is descriptive only. `CLOSED_SOURCE` does not promote source into deployed, physical, independently assured, signed, piloted, store-approved, or released status.

<!-- module-controls:docs-index:start -->
## Active module and closure controls

1. `modules/modules.json` — single active module registry; older layered registries are historical lineage.
2. `modules/README.md` — 26 module-specific engineering handoff pages.
3. `EXTERNAL_CLOSURE_PROGRAM.json` — authority-owned gate inventory and exact evidence requirements.
4. `operations/EXTERNAL_CLOSURE_ORCHESTRATION.md` — operator workflow for authentic E5–E7 closure.
5. `development/RELEASE_VERSIONING.md` — repository version and promotion contract.
6. `development/SOURCE_ARTIFACT_ARCHIVAL.md` — externally signed Artifact archival and revalidation.

Run the generator and semantic validator before proposing a registry, module, contract, or closure-program change.
<!-- module-controls:docs-index:end -->

## Layered machine truth

### G9 authenticated evidence and latest-head custody

G9 adds authenticated external-evidence and exact-head CI-custody semantics without manufacturing external facts:

- `G9_STATE.json`
- `G9_MODULES.json`
- `G9_GAP_LEDGER.json`
- `development/G9_TERMINAL_EXTERNAL_CLOSURE.md`
- `development/G9_FILESYSTEM_CUSTODY_HARDENING.md`
- `adr/ADR-0004-external-evidence-authentication.md`
- `adr/ADR-0005-latest-head-ci-concurrency.md`
- `adr/ADR-0006-external-evidence-filesystem-custody.md`
- `adr/ADR-0007-evidence-object-identity-and-bounded-custody.md`

`services/qualification/test_g9_metadata.py` verifies the G9 layer, source inheritance, filesystem custody, and private-key exclusion. `services/qualification/test_ci_latest_head_custody.py` verifies stale-run cancellation and exact-source identity in all seven jobs.

### G10 complete-closure semantics

G10 adds strict all-authority closure and trusted validation semantics:

- `G10_STATE.json`
- `G10_MODULES.json`
- `G10_GAP_LEDGER.json`
- `development/G10_AUTHORITY_QUORUM_AND_REVIEW_INTEGRITY.md`
- `development/G10_AUTHORITY_SEAT_AND_REPOSITORY_ADMISSION_HARDENING.md`
- `development/G10_TRUSTED_VERIFIER_AND_CONTRACT_BINDING.md`
- `development/G10_LEXICAL_VALIDATION_CUSTODY.md`
- `adr/ADR-0008-authority-quorum-and-review-set-integrity.md`
- `adr/ADR-0009-trusted-verifier-and-contract-content-binding.md`
- `adr/ADR-0010-lexical-validation-custody.md`

The layer covers all-class authority quorum, exact class-scoped claims, ordered final reviewer-set binding, canonical acceptance context, trusted current time, fixed `/usr/bin/openssl`, canonical contract-content signatures, no-follow lexical scope, transaction-wide ancestor identity pinning, and recursive committed-package admission.

Tests include:

- `services/qualification/test_g10_metadata.py`
- `services/qualification/test_external_evidence_complete_closure.py`
- `services/qualification/test_external_evidence_authority_seat_scope.py`
- `services/qualification/test_external_evidence_runtime_policy.py`
- `services/qualification/test_external_evidence_lexical_scope_policy.py`
- `services/qualification/test_external_evidence_contract_binding.py`
- `services/qualification/test_external_evidence_repository_admission.py`

### Active remediation

The active remediation layer closes repository-controlled source slices while preserving the external claim ceiling:

- `development/2026-09-03_BLOCKER_EXECUTION_PLAN.md`
- `development/ADMISSION_CONTINUITY.md`
- `development/AUTHENTICATED_MODEL_INGRESS.md`
- `development/AUTHENTICATED_PRINCIPALS.md`
- `development/AUTHENTICATED_REALTIME_INGRESS.md`
- `development/CAPABILITY_REVOCATION_SAFETY.md`
- `development/DATA_SKILL_RUNTIME.md`
- `development/DURABLE_CAPABILITIES.md`
- `development/DURABLE_IDENTITY.md`
- `development/DURABLE_MEMORY.md`
- `development/DURABLE_MODEL_GATEWAY.md`
- `development/GOOGLE_CALENDAR_CAPABILITY.md`
- `development/HG0087_PRODUCTION_IMPLEMENTATION.md`
- `development/IDENTITY_ENROLLMENT_FRESHNESS.md`
- `development/MEMORY_COMPONENT_IDENTITY.md`
- `development/MODEL_RECOVERY_INVENTORY.md`
- `development/MUTATION_AUTHORITY.md`
- `development/PACKAGE_TRANSPARENCY.md`
- `development/PACKAGE_TRANSPARENCY_CONSISTENCY.md`
- `development/REALTIME_ADMISSION.md`
- `development/REALTIME_PROVIDER_BINDING.md`
- `development/REFERENCE_RUNTIME_HARDENING.md`
- `development/SERVER_PROVIDER_BOUNDARY.md`
- `development/SIGNED_SKILLS.md`
- `development/SIGNED_SKILL_SCHEMA_INTEGRITY.md`
- `development/SIGNED_SKILL_STATE_CONTINUITY.md`
- `development/SOURCE_COVERAGE_AND_STATE.md`
- `development/SPEECH_BOOTSTRAP_CUSTODY.md`

## Device and protocol documentation

- `G1_BLE_CONNECTION.md`
- `G1_BLE_CONNECTION.en.md`
- `../contracts/g1-ble-protocol-v1.json`
- `../schemas/glasses-event.schema.json`
- `operations/DEVICE_QUALIFICATION_RUNBOOK.md`

The source documents protocol and failure semantics. Vendor protocol authority, firmware compatibility, RF behavior, latency, power, thermal, soak, secure boot, OTA, recovery, and rollback require physical or vendor evidence.

## Operations

- `operations/CREDENTIAL_INCIDENT_RUNBOOK.md`
- `operations/DATA_SKILL_RUNTIME_RUNBOOK.md`
- `operations/DEVICE_QUALIFICATION_RUNBOOK.md`
- `operations/DURABLE_CAPABILITY_RUNBOOK.md`
- `operations/DURABLE_MODEL_GATEWAY_RUNBOOK.md`
- `operations/GOOGLE_CALENDAR_CAPABILITY_RUNBOOK.md`
- `operations/HG0087_PRODUCTION_RUNTIME_RUNBOOK.md`
- `operations/IDENTITY_AUTHORITY_RUNBOOK.md`
- `operations/PACKAGE_TRANSPARENCY_RUNBOOK.md`
- `operations/PACKAGE_TRANSPARENCY_WITNESS_RUNBOOK.md`
- `operations/PRIVACY_SECURITY_REVIEW_CHECKLIST.md`
- `operations/PRODUCTION_CONTROL_PLANE_RUNBOOK.md`
- `operations/REALTIME_ADMISSION_RUNBOOK.md`
- `operations/REALTIME_AND_CAPABILITY_RUNBOOK.md`
- `operations/RELEASE_AND_ROLLBACK_RUNBOOK.md`
- `operations/REPOSITORY_GOVERNANCE_RUNBOOK.md`
- `operations/SIGNED_SKILLS_RUNBOOK.md`
- `operations/SIGNED_SKILL_SCHEMA_RUNBOOK.md`
- `operations/SIGNED_SKILL_STATE_RUNBOOK.md`
- `operations/SPEECH_BOOTSTRAP_RUNBOOK.md`
- `../evidence/external/README.md`

Runbooks define source-side procedures and evidence shapes. They are not proof that a provider, lab, reviewer, signing authority, pilot operator, vendor, or store executed the procedure.

## Architecture decisions

- `adr/ADR-0001-distributed-os-boundary.md`
- `adr/ADR-0002-codex-authority-boundary.md`
- `adr/ADR-0003-edge-runtime-language.md`
- `adr/ADR-0004-external-evidence-authentication.md`
- `adr/ADR-0005-latest-head-ci-concurrency.md`
- `adr/ADR-0006-external-evidence-filesystem-custody.md`
- `adr/ADR-0007-evidence-object-identity-and-bounded-custody.md`
- `adr/ADR-0008-authority-quorum-and-review-set-integrity.md`
- `adr/ADR-0009-trusted-verifier-and-contract-content-binding.md`
- `adr/ADR-0010-lexical-validation-custody.md`

A later plan or ADR must state what it supersedes and update the applicable current state, gap ledger, evidence index, module registry, validators, tests, and machine contracts in the same change.

## Machine contracts and schemas

Key composed contracts:

- `../contracts/hepta-glasses-runtime-v1.json`
- `../contracts/control-plane-v1.json`
- `../contracts/g1-ble-protocol-v1.json`
- `../contracts/durable-capability-v1.json`
- `../contracts/durable-memory-v1.json`
- `../contracts/durable-model-gateway-v2.json`
- `../contracts/realtime-admission-v1.json`
- `../contracts/realtime-speech-custody-v2.json`
- `../contracts/signed-skill-package-v1.json`
- `../contracts/signed-skill-transparency-v1.json`
- `../contracts/external-evidence-envelope-v1.json`
- `../contracts/release-gates-v1.json`
- `../contracts/qualification-slo-v1.json`
- `../contracts/main-branch-protection-v1.json`
- `../contracts/conformance/canonical-json-v1.json`

Key schemas:

- `../schemas/external-evidence-envelope.schema.json`
- `../schemas/external-authority-trust-registry.schema.json`
- `../schemas/release-evidence-bundle.schema.json`
- `../schemas/device-qualification-report.schema.json`
- `../schemas/tool-request.schema.json`
- `../schemas/tool-receipt.schema.json`
- `../schemas/decision-lease.schema.json`
- `../schemas/realtime-ticket.schema.json`
- `../schemas/skill-manifest.schema.json`
- `../schemas/memory-record.schema.json`

## Truth validation

`services/qualification/documentation_truth.py` and `services/qualification/test_documentation_truth.py` reject:

- disagreement over HG-0087 source closure;
- promotion of HG-0089 without Administration evidence;
- stale README/Current State phrases;
- required-check drift;
- transfer of a predecessor artifact to a successor;
- missing maturity stages or productization index entries;
- broken commit-to-artifact identity binding.

These checks are structural and semantic consistency controls. They do not issue any external authority or replace module-owner, security, hardware, provider, legal, accessibility, safety, signing, pilot, or store review.
