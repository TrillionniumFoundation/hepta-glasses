# Hepta Glasses OS — active repository source candidate

Hepta Glasses is a distributed AI-native companion platform for Even G1-class smart glasses. The repository contains a Flutter mobile edge runtime, Android/iOS BLE and speech adapters, deterministic policy/audit/tool execution, development cloud services, Skills/Memory components, qualification tooling, and authenticated evidence contracts.

The product boundary is explicit: this repository is **not** vendor-authorized G1 firmware, and repository source or CI cannot manufacture physical-device, provider, KMS/HSM, attestation, signing, independent-assurance, pilot, rollout, store, or other E5–E7 authority.

## Authoritative status

The live head and Git tree of open PR #127 identify the active successor source object. PR #127 targets `main` from `integration/hepta-main-convergence-20260912`. The live GitHub pull-request and commit readback—not a copied SHA in prose—determines the current source identity. The active successor remains `source_implemented`, not `ci_qualified`, `released`, or production-authorized, until one unchanged final head completes all seven jobs, yields a freshly inspected source Artifact, and receives an eligible non-author/non-latest-pusher approval.

The prior PR #114 object at commit `317ee1141ceac6df7d711aeaaca27b22d735e48d`, tree `51e673238d30b81ef8eb64b93eef14fc7bf850cb`, completed all seven jobs and produced source artifact `10098668276` with ZIP SHA-256 `6eac5358c5b0f1555043ac99250e583d5baeb7a89a2133365d72ad5bead7037c`. It is historical predecessor evidence only: it received artifact-integrity comments but no eligible `APPROVED` review, and neither its CI nor its Artifact attests PR #125, PR #126 and PR #127 or any later head.

The last independently qualified historical baseline remains PR #101 at:

- commit `35f01329262d6a137bfa3c7e95302a397ed32676`;
- tree `d585f78b8eddf4676bdee4d6f666a544f64a9f86`;
- canonical workflow run `34139161340` / #847, with all seven required jobs successful;
- source artifact `10025745282`, ZIP SHA-256 `baa9c218a779adb4713e5985d4109b20db70087e93fca34f2a9ba08e157af897`;
- independent artifact verification 39/39;
- exact-head Code Owner approval `5133811311`.

HG-0087 is `CLOSED_SOURCE`: all seven repository-controlled implementation slices are present with executable repository tests. That status does **not** mean deployment or product release is complete. `HG-0089` remains `BLOCKED_ADMIN_SETTING` until the complete canonical `main` protection contract is applied and independently read back, followed by ordinary protected adoption and new exact-`main` evidence.

## Current closure campaign

The dependency-ordered path for every remaining blocker is:

- `docs/development/2026-09-09_FULL_GAP_CLOSURE_PLAN.md` — exact execution DAG for issues #82, #84–#96 and #102;
- `docs/operations/FULL_GAP_CLOSURE_CONTROL_BOARD.md` — accountable role, next non-substitutable action and required acceptance object for every open gap;
- `docs/development/2026-09-09_SOURCE_DEEPENING_WORK_PACKAGES.md` — product identity, G1 protocol, mobile architecture, behavioral testing, observability, native provenance and product UX work packages;
- `docs/development/MODULE_DOCUMENTATION_COMPLETENESS_STANDARD.md` — semantic standard distinguishing generated handoffs from complete owner-authored technical specifications;
- `docs/development/MODULE_DOCUMENTATION_DEPTH_AUDIT_2026-09-09.md` — 26-module depth assessment and P0/P1/P2 documentation backlog;
- `.github/SECURITY.md` and `.github/CONTRIBUTING.md` — private-reporting, containment, review, merge and evidence-boundary rules.

The campaign preserves the no-bypass rule. Repository changes can close source preparation only; Administration, independent approval, external trust roots, provider facts, physical measurements, vendor authority, signing, assurance, pilot and store decisions must come from their real owners.

## Start here

- `docs/CURRENT_STATE.md` — current source, governance, platform, and external-authority truth.
- `docs/PROJECT_STATE.json` — machine-readable status and last-qualified baseline.
- `docs/REMEDIATION_GAP_LEDGER.json` — active repository remediation ledger.
- `docs/HG0087_IMPLEMENTATION_STATUS.json` — seven source-closed implementation slices and their remaining external requirements.
- `docs/MATURITY_MODEL.md` — separate design, source, CI, integration, physical, pilot, and release maturity.
- `docs/development/2026-09-08_PRODUCTIZATION_ROADMAP.md` — prioritized path from source candidate to product qualification.
- `docs/development/2026-09-09_FULL_GAP_CLOSURE_PLAN.md` — operational dependency graph for full closure.
- `docs/operations/FULL_GAP_CLOSURE_CONTROL_BOARD.md` — live authority and evidence handoff board.
- `docs/development/2026-09-09_SOURCE_DEEPENING_WORK_PACKAGES.md` — source-level deepening packages from product identity through UX.
- `docs/development/MODULE_DOCUMENTATION_COMPLETENESS_STANDARD.md` — required dimensions for detailed module documentation.
- `docs/development/MODULE_DOCUMENTATION_DEPTH_AUDIT_2026-09-09.md` — current module documentation-depth result.
- `docs/MODULE_COVERAGE.json` — compatibility pointer to tracked-source ownership.
- `docs/MODULE_HANDOFF.json` and `docs/development/MODULE_HANDOFF.md` — primary technical handoff for all registered modules.
- `contracts/conformance/canonical-json-v1.json` — shared Dart/Python canonical JSON vectors.

<!-- module-controls:index:start -->
## Active module and closure controls

- `docs/modules/modules.json` — single active module ownership and handoff registry.
- `docs/modules/README.md` — per-module engineering documentation index.
- `docs/EXTERNAL_CLOSURE_PROGRAM.json` — machine-readable Administration, provider, device, assurance, firmware, signing, pilot, and store closure program.
- `docs/development/RELEASE_VERSIONING.md` — source-version and promotion authority.
- `docs/development/SOURCE_ARTIFACT_ARCHIVAL.md` — durable exact-head source-evidence custody.

Generated module pages and closure records do not elevate source into deployed, physical, independently assured, signed, piloted, store-approved, or released status.
<!-- module-controls:index:end -->

## Architecture boundary

```text
Even G1 left/right endpoints
        |
        v
Android / iOS BLE and speech adapters
        |
        v
Flutter mobile edge authority
  policy · leases · audit · task/effect state · display
        |
        +----------------------+
        |                      |
        v                      v
capability adapters       authenticated cloud control
        |                 identity · model · realtime
        v                      |
external systems              v
                         isolated specialist workers
```

The UI submits intent and renders typed results. Deterministic runtime code admits and commits local effects. Cloud services own durable identity, short-lived authority, provider routing, revocation, and long-running coordination. Models, Skills, MCP clients, and Codex workers may propose work; they do not grant themselves mutation, release, or merge authority.

## Current source capabilities

The source candidate includes:

- generation-, pair-, side-, and payload-bound dual-leg G1 transport;
- bounded request ownership, late-response quarantine, degraded-pair handling, and explicit indeterminate outcomes;
- assistant display, manual text, notification/whitelist, heartbeat, bitmap, microphone, LC3/RNNoise, and cross-platform speech source paths;
- fail-closed startup, policy/lease Tool Gateway, durable metadata-only audit, task/effect recovery, and reconciliation;
- durable reference implementations for identity, model requests, realtime admission, capabilities, encrypted Memory custody, and signed Skills;
- a narrow text-only model-provider adapter and owned-calendar create/get adapter;
- source SBOM, provenance, history scanning, native sanitizers, physical-trace evaluation, and release-gate tooling.

These are source capabilities. Production activation remains disabled or incomplete wherever the named external identity, provider, hardware, signing, or assurance authority is unavailable.

## Canonical validation

The repository workflow must execute these seven non-empty jobs on one unchanged head:

1. `repository-contracts`
2. `flutter`
3. `android-native`
4. `ios-native`
5. `native-sanitizers`
6. `secret-and-boundary-scan`
7. `source-evidence`

Repository contracts include documentation-truth, source-ownership, module-handoff, security-boundary, history, service, adapter, and production-authority checks. CI establishes at most E4. Physical devices, deployed infrastructure, independently administered trust roots, provider receipts, signed binaries, pilots, stores, and release decisions require separately authenticated evidence.

## Remaining non-source gates

The unresolved product blockers are deliberately not represented as missing source code:

- complete canonical `main` protection and ordinary protected adoption;
- an independently administered out-of-band Ed25519 authority registry;
- provider-side historical credential revocation;
- production model, realtime, speech, OAuth, Calendar/capability tenants and receipts;
- production KMS/HSM identities plus Android and Apple attestation;
- signed Android/iOS and physical G1 qualification;
- vendor firmware, secure boot, OTA, recovery, and rollback authority;
- independent security, privacy, legal, accessibility, and safety assurance;
- signed binaries, binary SBOM/provenance, pilot, kill-switch, staged rollout, rollback, and store approval.

There is no release-gate override. Mocks, simulators, screenshots, repository-generated keys, locally invented receipts, self-review, or administrator bypass cannot close those rows.

## P0–P3 successor execution

PR #127 is the protected convergence successor above PR #126; neither parent branch nor `main` is updated by this declaration. The work package is `docs/development/PRIORITY_EXECUTION_2026-09-12.md` and its operations handoff is `docs/operations/PRIORITY_EXECUTION_RUNBOOK.md`. The existing HG-0087 source status is not acceptance of this new delta, module semantic completeness, production integration or the operational deepening backlog. All successor qualification flags remain false.
