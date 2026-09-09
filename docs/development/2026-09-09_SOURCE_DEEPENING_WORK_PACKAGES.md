# Source-deepening work packages — 2026-09-09

Status: implementation backlog refining the P1/P2 recommendations without changing the external evidence ceiling.  
Parent execution plan: `docs/development/2026-09-09_FULL_GAP_CLOSURE_PLAN.md`.

These work packages improve maintainability, protocol clarity, test depth and product operability. They may be implemented as small independently reviewed pull requests. Completing them in source does not close provider, physical-device, vendor, assurance, signing, pilot or store gaps.

## WP1 — Product identity convergence

### Objective

Replace inherited demo identities with one reviewed product identity before production OAuth, signing, storage, telemetry or store registrations become expensive to migrate.

### Required inventory

Record the current and target values for:

- Dart package/import name;
- Android namespace, application ID, manifest label, Keystore aliases and package-visible integrations;
- iOS bundle ID, display/bundle names, Keychain access groups and entitlements;
- URL schemes, universal/app links and OAuth redirect URIs;
- service audiences, token issuers, provider client registrations and attestation application identities;
- log subsystem/category names, database component IDs, telemetry environment and release channels;
- store listing, signing, update and rollback identities.

### Migration rules

1. Freeze the target naming contract before provider or store production registration.
2. Change namespace/package identity atomically where partial movement would break JNI, MethodChannel, attestation, Keychain/Keystore or OAuth bindings.
3. Preserve explicit migration for durable local data and revocation state; never silently treat old storage as a fresh authority database.
4. Add negative tests for old/new identity confusion and wrong-app attestation.
5. Bind release notes, rollback behavior and provider redirect changes to the same reviewed candidate.

### Exit criteria

No production-facing identifier contains `demo`, `example` or an inherited upstream package name unless explicitly retained as a compatibility alias with an expiry and migration owner.

## WP2 — Versioned G1 protocol package and authoritative readback

### Objective

Move protocol truth out of scattered Dart/Kotlin/Swift/C constants into one versioned contract with generated or mechanically checked cross-language implementations.

### Required protocol content

For every command and event document:

- command byte, direction, side/pair requirement and minimum firmware;
- complete byte layout, integer endianness, encoding, limits and reserved fields;
- MTU, fragmentation, packet sequence, terminal marker, CRC and timeout rules;
- ACK/NACK values and exact error meaning;
- idempotency/replay classification and whether readback exists;
- transaction or effect identity, generation and pair binding;
- left/right ordering and partial-pair semantics;
- capability discovery, firmware compatibility and deprecation policy;
- golden vectors consumed by Dart, Kotlin, Swift and native tests.

### Readback improvement

Prioritize firmware/vendor support for operation IDs and state queries for display, microphone mode, notifications, whitelist and bitmap state. Until available, preserve indeterminate outcomes and expose user/operator reconciliation instead of blind retries.

### Exit criteria

A protocol change cannot merge unless schema/contract, generated/checking code, all language vectors, feature documentation, firmware matrix and compatibility notes change together.

## WP3 — Mobile application boundary refactor

### Objective

Reduce global singleton coupling and separate presentation, application use cases, domain state machines and platform adapters.

### Target layering

```text
Flutter presentation
  -> application use cases
  -> domain state machines and typed contracts
  -> Android/iOS/G1/cloud adapters
```

### Required splits

Decompose the current assistant path into bounded components:

- assistant-session coordinator;
- speech-capture and transcription session;
- model conversation gateway;
- display pagination controller;
- touch interaction state machine;
- assistant-history repository;
- connection and permission coordinator.

Widgets must not construct or directly own security-critical dependencies. Application services return typed receipts and immutable snapshots. Cancellation, page teardown, backgrounding and process death must invalidate stale callbacks without converting uncertain effects into success.

### Exit criteria

Core user journeys can be tested with injected clocks/adapters and no platform channels, while Android/iOS adapters have separate contract tests for authority identity and lifecycle behavior.

## WP4 — Behavioral test-depth gates

### Objective

Measure risk coverage rather than document length or green happy-path counts.

### Required additions

- parser and state-machine fuzzing for packet, strict JSON, lease, evidence and package boundaries;
- deterministic concurrency schedules for duplicate admission, revoke races, stale callbacks and final-commit windows;
- mutation testing on policy, retry safety, authority comparisons and error classification;
- end-to-end Flutter journeys for pairing, permission denial, one-leg degradation, background/foreground, process restart and recovery;
- Android OEM/SDK and iOS device/locale/interruption matrices;
- provider staging suites for timeout, quota, revoke, readback and tenant drift;
- signed-build install, upgrade, migration and rollback tests;
- nightly hardware-in-loop runs once a controlled lab exists.

### Gates

Define module-specific behavioral thresholds. Coverage numbers alone cannot pass a critical module; required negative scenarios and mutation survivors must be zero or explicitly risk accepted by the applicable independent owner.

## WP5 — Privacy-safe observability and SLOs

### Objective

Turn current safe event logging into an operated measurement and incident system without retaining sensitive content.

### Required metrics

- scan and complete-pair discovery success;
- per-leg and pair readiness latency;
- reconnect and retired-callback suppression;
- queue rejection, ACK timeout, late response and indeterminate effect rates;
- assistant first-audio, partial, final transcript, model and final-display latency percentiles;
- cancellation propagation and stale-result suppression;
- provider quota, timeout, revoke and reconciliation results;
- crash-free sessions, durable recovery outcomes and capacity/suspension events;
- handset/G1 battery and thermal impact;
- firmware/OS/device compatibility failures.

### Privacy rules

Use bounded opaque correlation/effect IDs and coarse approved dimensions. Do not log prompts, answers, raw audio, partial transcripts, credentials, notification/calendar contents, precise location, accessibility payloads or stable personal/device identifiers. Hashing low-entropy values is not sufficient anonymization.

### SLO process

Each SLO needs a measurement source, numerator/denominator, window, percentile, alert, stop threshold, owner and rollback action. Physical and provider SLOs require real measurements; source fixtures can only validate the evaluator.

## WP6 — Native dependency provenance and response

### Objective

Replace `NOASSERTION` native revisions with a reproducible, vulnerability-manageable supply-chain record.

### Required record per vendored component

- upstream repository and exact commit/tag;
- original archive or source-tree digest;
- supplier and complete license/notice files;
- import date and importer;
- local patch series and patch digests;
- platform source paths, build flags, compiler/NDK/Xcode versions and ABI targets;
- sanitizer, malformed-input and cross-platform parity coverage;
- SBOM package/file relationships;
- vulnerability-monitoring source, response owner and target timelines;
- upgrade, compatibility verification and rollback procedure.

### Migration

If the exact historical upstream revision cannot be recovered, record a one-time forensic comparison and adopt a known upstream baseline through a reviewed compatibility change. Do not invent a revision or relabel the current tree as unmodified upstream.

### Exit criteria

Every release binary can be traced to exact vendored source, local patches, build configuration, binary SBOM and provenance; vulnerability triage can determine whether a disclosed upstream defect applies.

## WP7 — Product UX, accessibility and diagnostics

### Objective

Replace protocol-demo surfaces with a product workflow that makes authority, privacy, degradation and recovery visible to the user.

### Required journeys

- onboarding, permission education and complete left/right pairing;
- per-leg state, firmware compatibility and degradation diagnostics;
- visible microphone/voice state, cancellation and privacy indication;
- account/provider configuration without exposing credentials;
- notification source consent and readable structured forms instead of raw JSON;
- explicit indeterminate/reconciliation messaging and safe recovery actions;
- export, deletion, account removal and support-diagnostic bundle;
- localization, dynamic type, contrast, screen reader, focus order and non-audio alternatives;
- safety controls for distraction, notification overload, emergency stop, battery and thermal conditions.

### Exit criteria

The declared accessibility/device/language matrix passes on signed physical builds and all user-visible error states identify a safe next action without claiming an uncertain effect failed.

## Delivery order

Implement WP1 and WP2 before locking production provider and signing identities. WP3 and WP4 should proceed together so refactoring retains behavior. WP5 instrumentation must exist before physical qualification and pilot. WP6 must complete before final binary SBOM/provenance acceptance. WP7 begins during source refinement and is accepted only through independent accessibility/safety review and physical/pilot evidence.
