# Hepta Glasses OS current state

Last updated: 2026-09-10
Canonical plan revision: `2026-09-01-g8`

## Source authority

The canonical G8 plan remains the base contract. G9, G10, G11 terminal-closure controls and the active remediation layer add authenticated evidence custody, complete-closure semantics, production-reference components and source hardening.

The live head and Git tree of open PR #125 identify the active successor source object. PR #125 targets `codex/hepta-main-convergence-20260909-v2` from `codex/hepta-identity-migration-20260910`. The live GitHub pull-request and commit readback, rather than a copied SHA in prose, determines the current source identity. Until one unchanged final head completes seven-job CI, fresh Artifact inspection and an eligible exact-head approval, the successor remains `source_implemented` and unqualified for product release.

The prior PR #114 object at commit `317ee1141ceac6df7d711aeaaca27b22d735e48d`, tree `51e673238d30b81ef8eb64b93eef14fc7bf850cb`, completed the seven canonical jobs and produced artifact `10098668276`, ZIP SHA-256 `6eac5358c5b0f1555043ac99250e583d5baeb7a89a2133365d72ad5bead7037c`. It is historical predecessor evidence only. It received bounded artifact-integrity comments but no eligible approval, and no result transfers to PR #125 or a later source head.

`main` remains the older protected baseline until the complete policy is applied and independently read back, and the final candidate is adopted through the ordinary protected route.

The last independently qualified historical baseline is PR #101:

- source `35f01329262d6a137bfa3c7e95302a397ed32676`;
- tree `d585f78b8eddf4676bdee4d6f666a544f64a9f86`;
- run `34139161340` / #847;
- seven non-empty canonical jobs with terminal success;
- artifact `10025745282`;
- artifact ZIP SHA-256 `baa9c218a779adb4713e5985d4109b20db70087e93fca34f2a9ba08e157af897`;
- independent artifact checks 39/39;
- exact-head Code Owner review `5133811311` by `Tomasrgbsf`.

A later candidate must obtain its own complete seven-job result, artifact verification and eligible review before becoming the independently qualified source baseline.

## Closure execution control

The remaining blockers are dependency ordered in:

- `docs/development/2026-09-09_FULL_GAP_CLOSURE_PLAN.md`;
- `docs/operations/FULL_GAP_CLOSURE_CONTROL_BOARD.md`;
- `docs/EXTERNAL_CLOSURE_PROGRAM.json`.

The sequence is: current source truth and exact-head qualification; canonical branch protection and protected adoption; independently administered trust registry; provider/KMS/attestation integration; physical G1 and speech qualification; vendor and independent assurance; production signing, pilot, rollback, rollout and store approval; final aggregate acceptance.

No source document, issue comment, checkbox or generated artifact can skip a required authority stage.

## Repository-side state

The canonical registry contains **26 modules**. `docs/modules/modules.json` is the active ownership and handoff source. `docs/MODULE_COVERAGE.json` is a compatibility pointer, and `docs/MODULE_HANDOFF.json` plus `docs/development/MODULE_HANDOFF.md` retain the handoff views.

Structural validators prove ownership, references, generated-page identity, declared dimensions and status agreement. They do not prove that owner-authored technical documentation remains semantically complete. `docs/development/MODULE_DOCUMENTATION_COMPLETENESS_STANDARD.md` now defines the required module-specific dimensions and independent review protocol.

Repository source includes:

- a fail-closed Flutter composition root, typed edge runtime, policy/lease Tool Gateway, bounded effect scheduler and durable metadata-only audit journal;
- exact G1 pair/generation/side/payload authority, independent left/right readiness, bounded native write queues, late-response quarantine, and degraded or indeterminate outcomes instead of blind replay;
- Android/iOS native builds, LC3/RNNoise sanitizer coverage, iOS framework-final speech handling, and a bounded Android ticket-bound PCM-to-ASR source path;
- durable SQLite reference components for identity, model requests, realtime activation, capabilities, encrypted Memory custody and speech bootstrap;
- a text-only foreground model-provider adapter and a narrow Google Calendar create/get adapter with conservative timeout and readback semantics;
- publisher-bound Ed25519 Skill packages, exact ZIP inventory, durable consent/version/revocation, a restricted zero-egress R0 data VM and signed-log inclusion verification;
- a fixed-executable Codex task supervisor, bounded process/output/resource custody and an exact-domain HTTPS broker, without claiming a complete arbitrary-code OS sandbox;
- a read-only, commit-pinned CI workflow covering repository/services, Flutter, Android, iOS, native sanitizers, boundary/history scanning and exact-head source evidence;
- G10 external-evidence validation with all-class quorum, exact claim partition, final review-set binding, trusted time, fixed system OpenSSL and descriptor/lexical filesystem custody;
- continuous committed-evidence discovery-to-validation custody through one bounded private read-only snapshot.

## Active source backlog

HG-0087 is `CLOSED_SOURCE`. Its identity, model, realtime, capabilities, speech, Skills and Memory slices are mapped in `docs/HG0087_IMPLEMENTATION_STATUS.json` and enforced by `services/qualification/test_hg0087_source_status.py`.

No repository-actionable remediation row remains `OPEN`. `docs/REMEDIATION_GAP_LEDGER.json` records the repository adoption row as `BLOCKED_ADMIN_SETTING`; authority-owned product rows remain blocked by real external inputs rather than missing repository-only implementation.

`CLOSED_SOURCE` means implemented source plus executable repository tests. It does not imply exact-head independent approval, protected-main adoption, deployment, physical qualification, independent assurance, signing, pilot, store approval or release.

## Platform truth

The project is a distributed companion/edge/cloud platform, not vendor G1 firmware. The repository contains no vendor-authorized bootloader, secure-boot roots, firmware signing authority, OTA authority, recovery authority or rollback authority.

Android PCM-to-ASR source components and authenticated lifecycle bindings exist, but production activation remains fail closed without a live authenticated bootstrap, configured speech tenant, same-generation decoded PCM delivery, provider finality, cancellation/revocation propagation and physical qualification. iOS speech likewise requires signed-device, OS, locale, interruption, latency, power and privacy qualification.

Mobile model traffic targets a Hepta-owned gateway or explicit development loopback; no permanent provider key belongs in the application bundle. Production mutations remain fail closed until identity-backed authority is composed.

## Audit, privacy and recovery truth

The local audit journal verifies its chain during initialization, reads and explicit verification. Its authenticated checkpoint fast path is a bounded-tail optimization, not a remote immutable root. Production still requires retention, rotation, capacity handling, export authorization, backup exclusion, periodic full verification, and an independently governed monotonic, WORM or remote anchor where required.

Raw audio and partial transcripts are active-session data. Assistant transcript/answer history is disabled at every start, enabled only by direct user action, process-memory only and destructively cleared on opt-out. Durable Memory stores ciphertext and metadata but depends on an external per-subject key service; fixture ciphers are not production custody.

A timeout after an effect may have started is indeterminate. Reconciliation is a read or query, never permission to replay a mutation. Revocation and cancellation prevent future admission but cannot retroactively erase bytes already accepted by a device or provider.

## Governance gate

Public `main` readback reports protection enabled but exposes only four required contexts:

- `repository-contracts`
- `flutter`
- `secret-and-boundary-scan`
- `source-evidence`

The canonical contract additionally requires `android-native`, `ios-native` and `native-sanitizers`, plus strict status checks, administrator enforcement, Code Owner and most-recent-push approval, stale-review dismissal, conversation resolution, linear history, disabled force-push/deletion and no bypass actor for adoption.

The managed GitHub integration can coordinate repository content and ordinary pull-request work but cannot read or write the complete protection endpoint; the detailed endpoint returns `403 Resource not accessible by integration`. Repository-role admin does not expand the GitHub App installation token. HG-0089/HG-0017 therefore remain blocked pending a short-lived Administration-authorized apply and independent full API readback. Directly updating `main`, relaxing protection or using administrator bypass would not close the row.

## External authority gates

Repository source cannot manufacture:

- an independently administered out-of-band Ed25519 authority registry;
- signed Android/iOS plus physical Even G1 qualification;
- production KMS/HSM and Android/Apple attestation receipts;
- provider-side historical credential revocation;
- real model, realtime, speech, OAuth and capability tenants and receipts;
- vendor firmware, secure-boot, signing, OTA, recovery and rollback authority;
- independent security, privacy, legal, accessibility and safety assurance;
- signed binaries, binary SBOM/attestation, pilot telemetry, kill-switch and rollback drills, staged rollout and store approval.

These remain `BLOCKED_EXTERNAL`, `BLOCKED_ADMIN_SETTING` or `BLOCKED_UPSTREAM` until their real issuing authorities provide authenticated evidence. E0–E4 never close E5–E7, and there is no release-gate override.
