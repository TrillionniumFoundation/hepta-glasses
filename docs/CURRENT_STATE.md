# Hepta Glasses OS current state

Last updated: 2026-09-07  
Canonical plan revision: `2026-09-01-g8`

## Source authority

The canonical G8 plan remains the base contract, while G9, G10 and the active
remediation layer add evidence authentication, complete-closure semantics,
production-reference components and source hardening. The live head and tree of
Draft PR #101 identify the active candidate; no hand-copied SHA in prose grants
authority. `main` remains an older baseline until the reviewed candidate is
intentionally adopted through the protected path.

Every source push invalidates prior exact-head workflow, artifact and review
credit. E4 exists only when one unchanged candidate completes all seven non-empty
CI jobs and the resulting `hepta-source-evidence-<sha>` artifact passes independent
content verification. Local runs, parent-commit artifacts, PR prose, cancelled
jobs, skipped jobs and self-written hashes are not E4.

## Current repository-side state

The active flattened registry contains **26 modules**. `docs/MODULE_COVERAGE.json`
owns tracked source paths, `docs/MODULE_HANDOFF.json` maps each module to a primary
development document, and `docs/development/MODULE_HANDOFF.md` is the human index.
The validators prove structural ownership, references, dimensions and status
agreement; module-owner semantic review remains necessary.

Repository source currently includes:

- a fail-closed Flutter composition root, typed edge runtime, policy/lease Tool
  Gateway, bounded effect scheduler and durable metadata-only audit journal;
- exact G1 pair/generation/side/payload authority, independent left/right
  readiness, bounded native write queues, late-response quarantine and explicit
  degraded or indeterminate outcomes instead of blind replay;
- Android/iOS native builds, LC3/RNNoise sanitizer coverage, iOS framework-final
  speech handling, and a bounded Android ticket-bound PCM-to-ASR transport
  component whose consumer activation remains disabled until authenticated
  bootstrap and decoded-stream integration are composed;
- durable SQLite reference components for identity, model requests, realtime
  activation, capabilities, encrypted Memory custody and speech bootstrap;
- a concrete text-only foreground model-provider adapter and a narrow Google
  Calendar create/get adapter, both retaining conservative timeout and readback
  semantics;
- publisher-bound Ed25519 Skill package verification, exact ZIP inventory,
  durable consent/version/revocation, a restricted zero-egress R0 data VM and
  signed-log inclusion verification;
- a fixed-executable Codex task supervisor, bounded process/output/resource
  custody and an exact-domain HTTPS broker, without claiming that these are a
  complete arbitrary-code OS sandbox;
- one read-only, commit-pinned CI workflow covering repository/service tests,
  Flutter, Android, iOS, native sanitizers, boundary/history scanning and exact-
  head source evidence;
- authenticated G10 external-evidence validation with all-class quorum, exact
  claim partition, final review-set binding, trusted current time, fixed system
  OpenSSL and descriptor/lexical filesystem custody;
- continuous committed-evidence discovery-to-validation custody through one
  bounded private read-only snapshot. HG-0092 is `CLOSED_SOURCE`; E4, independent
  review and adoption remain separate governance conditions.

## Active source backlog

`docs/REMEDIATION_GAP_LEDGER.json` is the active remediation truth. After the
HG-0092 custody closure, **HG-0087 is the only aggregate repository implementation
row still OPEN**. Its machine-readable slices are in
`docs/HG0087_IMPLEMENTATION_STATUS.json`.

HG-0087 remains open because implemented libraries are not yet one authenticated
production path. Remaining source/integration work includes:

- production account and device authentication feeding short-lived mobile
  mutation authority and downstream revoke consumers;
- live model, realtime and speech service composition with authenticated ingress,
  provider tenancy, bounded cancellation/recovery and encrypted metadata;
- OAuth consent/refresh-token vault integration, identity-backed capability
  leases and encrypted recovery payload custody;
- Android decoded PCM streaming into the ticket-bound ASR component, finality,
  cancellation, privacy and cross-platform session integration;
- arbitrary-code Skill execution behind namespaces/seccomp/cgroups or an
  equivalent hard isolation boundary, capability-mediated I/O and broker-
  exclusive egress;
- production per-subject Memory keys, authenticated ingress, backup anti-rollback
  and downstream deletion reconciliation.

Reference objects, mocks, unconfigured fail-closed adapters and interface
statements do not complete this row. Each source slice must retain tests,
contracts, migration rules and an operations contract.

## Current validation observation

The detached-descendant supervisor regression that failed run #717 was hardened
to prove that the child actually starts and to avoid coupling that cleanup test
to a shared-runner real-UID process count. The subsequent repository-contracts
lane passed the full service and adapter test suites. Later documentation/source
commits invalidate that run as final E4 evidence; the final unchanged head still
requires a fresh complete seven-lane result and content-verified artifact.

## Product and platform truth

The project is a distributed companion/edge/cloud platform, not vendor G1
firmware. The repository does not contain vendor-authorized bootloader, secure
boot, firmware signing, OTA, recovery or rollback authority. Android and iOS
source builds and simulators do not prove physical radio behavior, protocol
compatibility, latency, power, thermal or soak performance.

The Android PCM-to-ASR class is a bounded source component, not an enabled
production speech path. `startEvenAI` remains fail-closed on Android until an
authenticated one-shot bootstrap is obtained, decoded PCM is delivered under the
same generation/pair identity, cancellation is propagated and the final result
is emitted through the current speech event channel. iOS speech still requires
physical device, OS and locale qualification.

The mobile model path targets a Hepta-owned gateway or explicit development
loopback and does not embed a permanent provider key. Production startup keeps
mutation authority fail-closed until identity-backed authority is composed.

## Audit, privacy and recovery truth

The local audit journal verifies its chain on initialization, reads and explicit
verification. Its authenticated checkpoint fast path is a bounded-tail
optimization, not a remote immutable root. Production must define periodic full
verification, retention, rotation, capacity handling, export authorization,
backup exclusion and optionally a trusted monotonic, WORM or remote anchor.

Raw audio and partial transcripts are active-session data. Transcript/answer
history is disabled at every application start, can be enabled only by direct
user action, remains process-memory only and is destructively cleared on opt-out.
The durable Memory component stores ciphertext and metadata but depends on an
external per-subject key service; test ciphers are not production custody.

A timeout after an effect may have started is indeterminate. Reconciliation is a
read/query, never permission to replay a mutation. Revocation and cancellation
prevent future admission but cannot retroactively erase bytes already sent to a
remote provider or device.

## Governance and external gates

The public `main` branch response reports protection enabled but exposes only
four required contexts: `repository-contracts`, `flutter`,
`secret-and-boundary-scan` and `source-evidence`. The canonical policy additionally
requires `android-native`, `ios-native` and `native-sanitizers`, plus strict mode,
administrator enforcement, CODEOWNER and last-push approval, stale-review
dismissal, conversation resolution, linear history and disabled force-push and
deletion. The detailed protection endpoint is not readable through the installed
integration, so HG-0089/HG-0017 remain blocked pending administrator application
and complete API readback.

Repository source cannot manufacture the following authority-owned facts:

- signed Android/iOS plus physical Even G1 qualification;
- production KMS/HSM and Android/Apple attestation;
- provider-side historical credential revocation;
- real model, realtime, speech and OAuth/capability tenants and receipts;
- externally administered publisher/reviewer trust roots and independent review;
- vendor firmware, secure-boot, signing, OTA, recovery and rollback authority;
- independent security, privacy, legal, accessibility and safety assurance;
- signed binaries, binary SBOM/attestation, pilot telemetry, kill-switch,
  rollout/rollback execution and store approval.

These remain `BLOCKED_EXTERNAL`, `BLOCKED_ADMIN_SETTING` or `BLOCKED_UPSTREAM`
until their real issuing authorities provide authenticated evidence. E0–E4 never
close E5–E7, and there is no release-gate override.
