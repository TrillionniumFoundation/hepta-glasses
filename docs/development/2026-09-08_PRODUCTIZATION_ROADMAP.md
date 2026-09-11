# 2026-09-08 productization and blocker-closure roadmap

Status: prioritized execution plan after repository-controlled source closure.

This plan does not reopen source-closed gaps merely because external evidence is absent. It separates work that can be completed in the repository from transactions that require GitHub Administration, cloud/provider accounts, physical hardware, independent reviewers, vendor authority, signing authorities, pilot operators, or stores.

## Baseline

The last independently qualified source baseline is PR #101 at commit `35f01329262d6a137bfa3c7e95302a397ed32676`, tree `d585f78b8eddf4676bdee4d6f666a544f64a9f86`, run #847, artifact `10025745282`, and Code Owner review `5133811311`.

HG-0087 is `CLOSED_SOURCE`. HG-0089 remains `BLOCKED_ADMIN_SETTING`. Authority-owned E5–E7 rows remain external or upstream.

Any source successor must complete fresh exact-head CI, artifact verification, and eligible review before adoption.

## P0 — one authoritative truth and a safe adoption path

### P0.1 Documentation truth

- Maintain one machine-readable project state.
- Keep `README.md`, `CURRENT_STATE.md`, `PROJECT_STATE.json`, the HG-0087 slice status, and the remediation ledger semantically consistent.
- Reject stale statements such as “HG-0087 remains OPEN” when the machine status is `CLOSED_SOURCE`.
- Distinguish the last qualified baseline from an unqualified successor.
- Use `docs/MATURITY_MODEL.md` for product-stage claims.

Exit: documentation-truth tests pass in `repository-contracts`.

### P0.2 Canonical `main` protection

Administration must apply and independently read back `contracts/main-branch-protection-v1.json`:

- all seven exact required checks with strict mode;
- administrator enforcement and no bypass actor;
- at least one approval and Code Owner review;
- approval of the most recent reviewable push;
- stale-review dismissal and conversation resolution;
- linear history;
- disabled force-push and deletion.

Exit: complete sanitized API readback is independently accepted. `protected=true` or four visible contexts is insufficient.

### P0.3 Protected adoption

After P0.2:

1. move the final candidate out of Draft;
2. merge through the ordinary protected path with expected exact head;
3. do not directly update `main`, relax policy, dismiss valid objections, or use administrator bypass;
4. run all seven jobs on the resulting exact `main` SHA;
5. independently verify the new artifact;
6. record exact `main` commit, tree, run, artifact, and review.

Exit: HG-0089/HG-0017 governance evidence is accepted.

### P0.4 Out-of-band authority registry

An independent controller must provision the Ed25519 registry required by #96:

- real identity and role verification;
- proof of private-key possession;
- narrow authority classes and gap scopes;
- bounded validity, rotation, revocation, suspension, and audit;
- organizational independence rules;
- out-of-band authoritative registry digest;
- witnessed substitution, rotation, and revocation negatives.

Exit: the registry validates under its schema and protected out-of-band pin; no private key enters GitHub custody.

## P1 — make the G1 companion a qualified product core

### P1.1 Physical G1 transport and feature matrix

Execute signed Android/iOS tests against declared physical G1 hardware and firmware:

- discovery, pairing, connection readiness, disconnect, reconnect, and one-leg degradation;
- pair/generation/side/payload authority and stale-callback rejection;
- MTU, CCCD, queue, ACK, late/duplicate response, and indeterminate-write behavior;
- text, notification, whitelist, heartbeat, bitmap, microphone, and display paths;
- RF loss, backgrounding, process restart, device power cycle, and long soak;
- latency percentiles, power, thermal, and recovery accounting.

Exit: both platform reports pass the canonical SLO with `synthetic=false`, exact signed binaries, hardware/firmware identity, and independent acceptance.

### P1.2 Speech

Deploy the production speech boundary and qualify:

- authenticated one-shot bootstrap;
- exact session, assistant generation, BLE generation, pair, locale, expiry, and audio limits;
- LC3/PCM format, buffering, finality, cancellation, interruption, and stale-result fencing;
- real provider revoke/readback;
- Android/iOS device and locale matrices;
- first-audio, partial, final, cancellation, and end-to-end latency;
- retention, training-use, regional processing, deletion, and redacted observability.

Exit: #92 evidence is accepted under the external registry.

### P1.3 Production identity and provider integration

In a controlled staging/production environment:

- deploy KMS/HSM-backed identity and signing;
- integrate Android and Apple attestation;
- exercise nonce, replay, rotation, revoke, lost-device, and recovery paths;
- provision real model, realtime, speech, OAuth, and Calendar tenants;
- verify quotas, abuse controls, retention, billing, cancellation, timeout, revoke, and reconciliation;
- use opaque credential handles and KMS/secret references;
- run backup, restore, anti-rollback, and multi-instance failure drills.

Exit: #87–#90 and the provider portions of #92 have real issuer receipts and independent acceptance.

### P1.4 Testing depth

Add and enforce:

- cross-language golden vectors for G1 packets and authority identity;
- parser/state-machine fuzzing;
- deterministic concurrency and crash-window tests;
- critical-path mutation testing;
- module coverage thresholds;
- CodeQL and dependency-vulnerability gates;
- nightly hardware-in-loop qualification;
- real provider sandbox/staging integration suites;
- signed-build installation and upgrade/rollback tests.

Exit: quality gates measure behavioral risk rather than document volume.

## P2 — complete product identity, operations, and distribution

### P2.1 Product identity and UX

Unify:

- Dart package name;
- Android namespace/application ID;
- iOS bundle/display name;
- service identities, log categories, URL schemes, and release channels.

Complete:

- onboarding and permission guidance;
- device inventory and firmware compatibility;
- left/right degradation and connection diagnostics;
- privacy/microphone indication;
- account/provider configuration;
- export, deletion, and account-removal flows;
- accessibility, localization, and support diagnostics.

### P2.2 Observability and SLOs

Define and operate privacy-safe telemetry for:

- scan and connection success;
- readiness and reconnect latency;
- one-leg degradation;
- ACK timeout and indeterminate effects;
- speech/model latency and failure;
- cancellation and stale-result suppression;
- provider quota, revoke, and reconciliation;
- crashes, battery, thermal, and firmware compatibility.

Every metric binds a correlation/effect ID without retaining raw audio, credentials, notification bodies, or sensitive transcripts.

### P2.3 Assurance, vendor, and release

- obtain vendor firmware/secure-boot/OTA/recovery/rollback authority;
- complete independent security, privacy, legal, accessibility, and safety reviews;
- resolve or explicitly accept every material finding;
- build and sign final Android/iOS binaries;
- generate binary SBOM, provenance, and attestations;
- execute pilot, kill-switch, rollback, and staged rollout;
- obtain store/distribution approval;
- evaluate the product release bundle without override.

Exit: #93–#95 pass under the same unchanged candidate and the product reaches `released`.

## Execution ownership

| Blocker | Required executor |
|---|---|
| Source/document/test changes | repository maintainers |
| Branch protection and protected adoption | GitHub repository administrator plus independent API observer |
| Trust registry | independent release-security/assurance controller |
| Credential revocation | affected provider and incident owner |
| Model/realtime/speech/OAuth/capabilities | provider tenant owners and cloud security |
| KMS/HSM and attestation | KMS/HSM and platform-attestation owners |
| Physical qualification | controlled or independent hardware lab |
| Firmware authority | Even G1 vendor or delegated authority |
| Assurance | organizationally independent reviewers |
| Signing/pilot/stores | signing, release, pilot, rollback, and store authorities |

## Non-negotiable closure rule

A gap closes only when its named issuing authority provides authenticated evidence, the exact candidate identity remains bound, required claims and artifact digests verify, reviewer independence is satisfied, and the canonical validator accepts the package.

Source code, local tests, mocks, screenshots, self-issued keys, issue checkboxes, synthetic device traces, locally generated provider receipts, or administrator bypass cannot substitute for the required fact.
