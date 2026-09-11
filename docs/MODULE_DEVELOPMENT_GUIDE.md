# Hepta Glasses module development guide

Status: canonical repository-side module guide for plan revision `2026-09-01-g8`.

This document explains how the current source is partitioned, where authority lives, which contracts are normative, how concurrency and failure are handled, and what evidence is still external. It complements the architecture, threat, privacy, capability, BLE, operations, and release documents; it does not promote source evidence into physical-device or production-release evidence.

`docs/MODULES.json` is the machine-readable ownership and coverage index. Every entry points to one or more sections below. `tools/validate_repository_metadata.py` verifies that source roots, documentation references, tests, contracts, Gap Ledger evidence, and resume packages exist on the exact source tree.

## Shared engineering rules

1. Models, realtime providers, Skills, MCP clients, widgets, and Codex workers propose work; deterministic code admits and commits effects.
2. A mutation is schema-validated, policy-admitted, exact-argument-bound, journaled before effect, idempotency-keyed, deadline-bound, and reconciled when completion is uncertain.
3. Timeout, disconnect, process death, callback loss, and missing acknowledgement are not proof that a physical or external effect failed.
4. Production code fails closed when identity, durable audit, platform authority, secure storage, network isolation, or provider configuration is unavailable.
5. Raw audio, credentials, secrets, and sensitive content do not enter long-term memory, source, or ordinary audit payloads.
6. Source tests and digital twins establish E1-E3 only. Exact-head CI establishes E4 only. Physical devices, deployed infrastructure, independent assurance, signing, pilot, rollout, and store approval require E5-E7.
7. A module change must update its contracts, tests, documentation section, Gap Ledger rows, and Evidence Index when any claimed invariant or evidence ceiling changes.

<!-- module:mobile-shell -->
## Mobile shell

### Responsibility and boundary

The mobile shell owns process startup, Flutter presentation, user-triggered navigation, connection-status presentation, and dependency composition. It does not decide authorization and must not call provider endpoints or hold permanent credentials. `lib/bootstrap/hepta_bootstrap.dart` is the only composition root for journals, mutation authority, deterministic device effects, and the edge runtime. Widgets consume `HeptaRuntime.current` or a bounded application service; they do not construct security-critical dependencies.

### Entry points and flow

`lib/main.dart` initializes Flutter bindings, configures the development model-gateway boundary, obtains the platform application-support path, and delegates runtime construction to `HeptaBootstrap.initialize`. Failure to obtain durable state or initialize the authenticated journal renders `FailClosedStartupApp`, leaving device and assistant mutations disabled. After successful initialization, controllers are registered and `HomePage` becomes the presentation entry point.

The UI submits intent and renders receipts or state. It must distinguish rejected-before-write, succeeded, and indeterminate results. A busy indicator is not proof of completion. Navigation teardown must cancel timers and subscriptions without manufacturing a success receipt.

### State and concurrency

Legacy GetX and singleton facades remain compatibility seams. New work should move state behind injected coordinators and immutable snapshots. A widget must check `mounted` after asynchronous work, release busy state in `finally`, and avoid installing more than one BLE callback owner. Long-running assistant, text, and bitmap operations carry explicit generation or effect scope.

### Security and privacy

No provider key, refresh token, release key, transcript body, notification body, or raw audio belongs in widget logs. History retention is disabled on every start, opt-in only, process-memory only, and destructively cleared on opt-out.

### Verification and change checklist

Run Flutter formatting, analyzer, unit/widget tests, Android/iOS builds, and startup-failure tests. A shell change must preserve the single composition root, fail-closed startup, accessibility labels, cancellation, and typed receipt handling. Release packaging, signing, store metadata, accessibility review, and a real device matrix remain external.

<!-- module:edge-runtime -->
## Edge runtime

### Responsibility and boundary

The edge runtime is the final mobile authority for local device effects and durable task state. It owns typed contracts, task lifecycle, effect scheduling, display composition, scope generations, and the orchestration seam between policy, audit, transport, and feature adapters.

### Interfaces and data flow

`HeptaRuntime` registers a bounded set of `ToolSpec` handlers. Public application methods build canonical arguments and derive an idempotency key from action, authorized device, effect scope, generation, and argument digest. The request then flows through `ToolGateway`, `PolicyEngine`, durable audit, `DeviceEffectScheduler`, and a native-effect adapter. Handlers return structured results rather than ambiguous booleans.

`TaskEngine` and `AssistantSessionCoordinator` provide state-machine boundaries. `DisplayComposer` transforms display cards into deterministic pages. `Clock` is injectable so expiry, timeout, and recovery tests are deterministic.

### Concurrency and failure semantics

The scheduler bounds physical work and shutdown. Scope generations fence stale asynchronous completions. A deadline that expires after preparation produces an indeterminate receipt, not a retryable failure. Cancellation prevents future work but cannot erase an already prepared or accepted effect. Process recovery replays metadata, consumed leases, terminal receipts, and prepared-without-terminal work.

### Security and privacy

The runtime receives an external `MutationAuthorityProvider`; it cannot synthesize authentication, device identity, user presence, biometric proof, or production leases. Audit envelopes contain identifiers and digests, not sensitive arguments.

### Verification and change checklist

State transitions require positive, negative, cancellation, timeout, replay, and crash-window tests. A new effect requires a typed spec, exact argument validation, policy tier, durable preparation, typed adapter, reconciliation behavior, tests, and documentation. Production authority and physical-effect evidence remain external.

<!-- module:policy-tool-gateway -->
## Policy, leases, and Tool Gateway

### Responsibility and boundary

This module is the sole admission and replay boundary for runtime mutations. It validates tool registration, request/spec agreement, authentication, risk tier, user presence, biometric requirements, exact lease binding, untrusted-content confirmation, deadlines, single-use consumption, idempotency, journal-before-effect, and reconciliation.

### Request and receipt contract

A `ToolRequest` carries request/task/device/action identity, canonical arguments, risk tier, mutation flag, idempotency key, deadline, trust class, and optional human-confirmation digest. A `DecisionLease` is bound to subject, device, task, allowed action, exact argument digest, policy hash, issuance and expiry time, and single-use semantics. A `ToolReceipt` separates status, policy reason, retry safety, external identity, and whether an effect may have occurred.

### Atomicity and concurrency

Identical in-flight requests join one future. Reuse of the same idempotency key with a different fingerprint fails before the handler. A permitted single-use lease is consumed before the first asynchronous journal or effect boundary, preventing two keys from spending the same authority concurrently. Prepared records precede mutating effects. Terminal-journal failure after an effect becomes indeterminate.

### Recovery and reconciliation

Recovery verifies the journal, rebuilds fingerprints and receipts, restores consumed leases, and marks prepared-without-terminal effects indeterminate. Reconciliation is an authoritative read/query. It is not another mutation attempt. A recovered request may use only a recovery-safe reconciler because sensitive arguments are intentionally absent from audit.

### Security and tests

R4 is denied in the consumer profile. Untrusted content cannot supply authority; an exact user confirmation digest is required where allowed. Tests must cover malformed requests, unknown tools, lease drift/expiry/reuse, concurrent duplicates, prompt injection, handler timeout, terminal audit failure, recovery, and reconciliation.

<!-- module:audit-journal -->
## Durable audit journal and checkpoint authentication

### Responsibility and format

The journal records metadata-only decision, preparation, terminal, recovery, and reconciliation facts in append-only canonical JSONL. Every record includes sequence, UTC timestamp, event type, payload, previous hash, and hash. File and record sizes are bounded, final records must be newline-complete, and the full chain is verified on initialization, explicit verification, and reads.

### Append fast path

Normal append uses an authenticated checkpoint produced by Android Keystore or the iOS device-bound Keychain/CryptoKit signer. The process-trusted head, checkpoint MAC, file length, filesystem change metadata, and terminal record must agree. A cache miss, metadata change, legacy checkpoint, or anchor drift triggers complete chain verification. This is an authenticated-tail optimization, not a claim that every ordinary append rescans every prior byte.

An attacker able to modify journal contents and perfectly restore all observed filesystem metadata may defer middle-record detection until the next explicit full verification. Production assurance should therefore define periodic full verification and may add immutable segments, remote root anchoring, WORM retention, or a trusted monotonic anchor.

### Crash and capacity behavior

Writes are serialized process-wide per path and protected by an OS file lock. Data is flushed before checkpoint replacement. Missing checkpoints on a non-empty journal, torn tails, invalid MACs, oversized records, capacity exhaustion, and legacy checkpoints without explicit migration fail closed. A failed terminal append after a prepared effect cannot make the effect retryable.

### Privacy, operations, and tests

Audit payloads contain no prompts, transcripts, credentials, notification bodies, locations, or raw audio. Production must define retention, export authorization, rotation, capacity alerts, backup exclusion, migration, and incident handling. Tests cover concurrent writers, corruption, equal-length tampering, torn tails, checkpoint drift, legacy migration, bounded capacity, and fast-path/full-verification counters.

<!-- module:g1-transport -->
## G1 transport and dual-leg BLE authority

### Responsibility and authority identity

The G1 transport owns scanning, pairing, connection generations, left/right readiness, native callback ownership, request correlation, write serialization, idempotency, acknowledgements, uncertain-write quarantine, degraded pair receipts, and reconciliation. The authoritative write identity is:

```text
(pair identity, connection generation, side, caller key, SHA-256(device bytes))
```

A response is authoritative only when it contains a positive generation and exact non-placeholder pair identity matching the captured request authority.

### Layering

`EvenG1Transport` is the runtime adapter. `BleManager` owns Flutter-side native-channel state, ACK slots, heartbeat scheduling, and per-leg quarantine. Android owns generation-captured GATT objects, service/characteristic/CCCD/MTU readiness, and bounded serialized writes. iOS owns immutable `PeripheralAttemptToken` delegates and a retired-peripheral barrier. `DualLegCoordinator` aggregates exact left/right receipts without treating one-leg success as pair success.

### Failure and retry

Authority mismatch or explicit native rejection before write is retryable only after reacquiring authority. Timeout after native acceptance, missing ACK, malformed post-write response, or unknown native completion is indeterminate. The exact generation/side/command is quarantined until a matching late response, authoritative reconciliation, retirement of that generation, or terminal disposal. Disconnecting one leg cannot release quarantine on the other.

### Verification and evidence ceiling

Hostile tests cover stale callbacks, unknown peripherals, cross-side/generation/pair key reuse, payload drift, unscoped responses, opposite-leg disconnect, queue limits, and reconnect barriers. Physical protocol compatibility, loss, latency, power, thermal, soak, pair stability, and firmware authority remain E5/upstream gates. `docs/G1_BLE_CONNECTION.md` is the detailed protocol document.

<!-- module:g1-protocol-features -->
## G1 protocol and device feature delivery

### Responsibility

This module encodes and delivers microphone, assistant display, manual text, heartbeat, exit-mode, notification, whitelist, and bitmap commands. Protocol code creates bounded packets; application services decide sequencing and paging; the runtime admits effects; transport code owns physical certainty.

### Packet and state rules

Packet count, sequence, payload length, page count, command byte, terminal ACK, and CRC responses are validated before success is returned. Text and assistant pages use generation-fenced timers and only advance after acknowledged delivery. Bitmap transfer validates source size, chunk order, native acceptance, finish reply, and CRC reply. Heartbeat scheduling is non-overlapping and retries only outcomes whose typed result proves no write occurred.

### Failure semantics

A multi-packet partial write is indeterminate. A left-leg success followed by right-leg uncertainty is a degraded pair effect requiring reconciliation. Feature code must never flatten a `DeviceEffectResult` or `ToolReceipt` into a boolean before deciding retry safety. Firmware readback unavailability must remain explicit.

### Security and tests

Asset paths are allowlisted, notification/whitelist inputs are bounded, and all device mutations pass the runtime. Tests cover invalid packet bounds, malformed finish/CRC responses, paging cancellation, microphone retry safety, heartbeat retry safety, dual-leg partial application, and receipt conversion. Vendor command authority and physical display/notification behavior remain external.

<!-- module:assistant-speech -->
## Assistant, speech, and mobile model gateway

### Responsibility and lifecycle

The assistant module coordinates wake/gesture, native assistant start, microphone admission, speech finalization, model request, cancellation, answer rendering, paging, barge-in fencing, and cleanup. An `AssistantSessionToken` and generation identify every active operation.

### Data flow

A native event begins a runtime session. The microphone is opened through policy and Tool Gateway. Speech events are accepted only for the current generation and only framework-final iOS transcripts become final text. The mobile model client calls a Hepta-owned HTTPS gateway or explicit loopback development endpoint; it never embeds a provider endpoint or permanent provider key. The answer is displayed through the runtime and completion is recorded only after the final page is acknowledged.

### Cancellation and retry

Start/stop events are debounced. Recording, speech-finalization, model, and paging timers are bounded. Model requests carry a cancellation token. A stale generation cannot publish transcript, answer, page, or completion. Microphone retries occur only after a `retrySafe` pre-write rejection; an uncertain microphone write stops and requires reconciliation. Barge-in or cancellation invalidates later callbacks but does not erase a possibly committed effect.

### Privacy and platform truth

Raw audio and partial transcripts are active-session memory only. Transcript/answer history is disabled by default, direct-user opt-in only, process-memory only, and immediately deleted on opt-out. Android currently has LC3 decoding but no production PCM-to-ASR adapter, so voice activation fails closed. Production provider retention, abuse controls, live receipts, iOS locale/device coverage, and physical latency/privacy evidence remain external.

<!-- module:android-native -->
## Android native integration

### Responsibility

Android native code owns runtime permission checks, BLE scanning and pairing, GATT connection state, generation-captured callbacks, service and characteristic discovery, CCCD notification enablement, MTU negotiation, initialization writes, serialized command writes, LC3/RNNoise native processing, application-support path exposure, and Keystore-backed audit checkpoint HMAC.

### Threading and ownership

Every selected GATT belongs to the current pair and generation. A stale callback closes or ignores its old object before mutating readiness or publishing Flutter state. A leg is ready only after all required discovery and initialization stages. Writes enter a bounded queue and validate expected generation and pair identity again immediately before native acceptance.

Decoded background work rechecks authority before emitting events. MethodChannel replies must distinguish pre-write rejection from possible post-write completion.

### Build, security, and tests

The Android build uses a fixed application ID, no release debug-signing fallback, native CMake inputs, and unit tests. Keystore key material never enters Dart. Required tests cover pair parsing, generation ownership, readiness, queue bounds, authority mismatch, LC3 bounds, sanitizer execution, and checkpoint signing. Production signing, Play Integrity, Android ASR, physical G1 qualification, OEM/device coverage, power, and thermal evidence remain external.

<!-- module:ios-native -->
## iOS native integration

### Responsibility

iOS native code owns BLE discovery, immutable connection-attempt delegates, selected-peripheral state, notification readiness, bounded writes, LC3/PCM conversion, system speech recognition, application-support path exposure, and Keychain/CryptoKit-backed audit checkpoint HMAC.

### Callback authority

Each side and attempt has a token containing peripheral identity, side, generation, and nonce. Service, characteristic, notification, value, and write callbacks may mutate state only when the token is current and the exact peripheral object remains selected. Unknown peripherals have no side. Cancelled identifiers enter a retired barrier and cannot be reassigned until the old terminal central-manager callback is consumed.

### Speech and security

Only a framework-final transcript is emitted as final; bounded partials are discarded on timeout or error. Old-attempt audio cannot enter a current speech session. Keychain audit keys are device-bound and never returned to Dart. Permission denial and unsupported locale/device behavior fail closed.

### Verification and external gates

XCTest covers stale callbacks, unknown ownership, retired barriers, side isolation, and native processing. Simulator build success is E3, not physical evidence. App Attest/DeviceCheck, signing, real G1 traces, locale/device matrix, battery, thermal, and store review remain external.

<!-- module:digital-twin -->
## G1 digital twin and fault injection

### Responsibility

The digital twin is a deterministic test transport for retry, idempotency, dual-leg degradation, disconnect, and acknowledgement-loss scenarios. It is not a firmware emulator and must never be indexed as physical evidence.

### Authority parity

The twin uses the same composite authority domain as production transport: pair identity, positive connection generation, side, caller key, and payload digest. Reuse of a complete scope with changed bytes fails closed. A receipt replays without another simulated write. Advancing generation optionally selects a new pair and retires prior receipts, proving that old results cannot suppress a new authority-domain write.

### Fault model

Pre-write timeouts are retry-safe and do not create a write. Injected acknowledgement loss applies the write and returns an indeterminate result. Side disconnects are explicit. Negative acknowledgement injection is deterministic and separately classified. Every simulated write records side, bytes, key, sequence, generation, and pair.

### Verification and evidence ceiling

Tests directly exercise cross-side, cross-generation, cross-pair, payload-drift, replay, pre-write timeout, acknowledgement loss, and single-leg degradation. The twin supplies E2 evidence only; protocol compatibility, timing distributions, RF loss, firmware behavior, power, thermal, and soak require physical G1 evidence.

<!-- module:model-gateway-service -->
## Development model gateway service

### Responsibility and boundary

The bundled Python service proves that the mobile application calls a Hepta-owned gateway rather than a provider endpoint. It validates a bounded JSON request, requires a sufficiently long bearer token, suppresses content logging, and returns a deterministic development answer. It is not a production model service.

### API and failure behavior

`GET /healthz` returns bounded service health. `POST /v1/chat` accepts only `question`, optional `task_id`, and bounded `context`; unknown fields, invalid UTF-8/JSON, missing authorization, and oversized bodies fail with stable errors. The service does not log request paths, headers, prompts, or response content by default.

### Production replacement contract

A production replacement must preserve the mobile API boundary while adding workload identity, KMS-managed provider references, tenant isolation, quotas, retention policy, abuse controls, redacted observability, provider timeout/cancellation mapping, authoritative request receipts, rollout, and revoke. The deterministic service may be used in local tests only.

<!-- module:identity-control-plane -->
## Identity control plane

### Responsibility

The reference identity module models device registration, subject/device binding, active/lost/revoked states, key-ID signing, short-lived access claims, session and token identifiers, key rotation, token/session/device/subject revocation, and sliding-window rate limits.

### Data and concurrency

Reference stores are protected by process locks but are in-memory. Device reactivation after lost/revoked state requires an explicit recovery path. Token verification checks signature, exact claims, issuer, audience, timestamps, maximum TTL, scopes, active device binding, and revocation. Key ID and signing secret are read atomically during issuance.

### Production requirements

Production must replace process memory and raw HMAC keys with a durable replicated registry, KMS/HSM signing or standards-based identity service, platform attestation verification, revocation propagation, service identity, audit export, recovery workflow, backup/restore, and operational SLOs. No mobile or repository path may contain permanent signing material.

<!-- module:realtime-control-plane -->
## Realtime control plane

### Responsibility

The realtime broker verifies a short-lived Hepta access token, rate limit, device binding, requested scope subset, provider profile allowlist, and TTL before issuing a one-time bootstrap ticket. It tracks connection/listening/responding/interruption/closed/revoked states and generation-fenced barge-in.

### Atomicity and lifecycle

Ticket activation and consumed-token recording occur under one lock so concurrent activation cannot spend the same ticket twice. State transitions require the current generation. Interrupt increments generation and invalidates prior transcript, audio, tool, display, and completion events. Revocation is terminal for the session.

### Production requirements

The reference broker is in-memory and provider-neutral. Production requires durable or reconstructible session state, a server-side provider exchange, credential vault, OAuth registration where applicable, network policy, quotas, telemetry, cancellation propagation, timeout reconciliation, multi-region behavior, revoke drills, and authoritative receipts. Provider keys never cross into the phone bundle.

<!-- module:capability-control-plane -->
## Capability control plane and adapters

### Responsibility

The capability gateway admits typed calendar, reminder, notification, location, storage, accessibility, and future operations behind exact schemas, risk tiers, trust classes, single-use leases, idempotency, metadata-only audit, and authoritative reconciliation.

### Atomicity and effect custody

Same-key/same-fingerprint requests coalesce; same-key/different-fingerprint requests fail. Mutation admission, lease reservation, and prepared audit occur under a lock before the external adapter executes. An indeterminate adapter result is reconciled by external ID when the adapter supports it. A timeout alone never authorizes a second mutation.

### Prompt-injection boundary

Notification, document, webpage, transcript, model, Skill, or tool content is untrusted. It may populate proposed arguments but cannot grant authority. R3 requires biometric proof; R4 remains disabled. OAuth refresh tokens remain server-side behind opaque handles.

### Production requirements

The in-memory reminder adapter is a deterministic stand-in. Each production capability requires provider registration, scoped consent, vault-backed credential handle, typed adapter, authoritative receipt, revoke, timeout reconciliation, audit export, rate limits, observability, and integration tests against the real provider.

<!-- module:skills-registry -->
## Skills registry

### Responsibility

The Skills registry validates publisher allowlists, key IDs, manifest signatures, semantic versions, package-byte digest, package size, entrypoint metadata, required capabilities, risk tier, data classes, network domains, timeout, installation consent, upgrade re-consent, downgrade prevention, conflict detection, resolution, and revocation.

### Trust and package custody

Source uses a deterministic HMAC trust store for tests. Production must use asymmetric publisher roots or an equivalent verifier so runtime verification does not possess publisher signing authority. The package digest is computed from actual bytes; a signed manifest cannot authorize substituted package content. R4 packages are denied.

### Upgrade and revoke

Added capability, data class, or domain requires explicit re-consent. A revoked Skill cannot resolve or reinstall without a separately governed recovery policy. Runtime execution must still pass capability policy; manifest admission does not itself grant a live lease.

### Production requirements

Add signed distribution metadata, encrypted content-addressed storage, malware review, sandbox execution, egress enforcement, dependency SBOM, staged rollout, kill switch, revoke propagation, audit, and independent review.

<!-- module:memory -->
## Memory and assistant-history retention

### Responsibility

The reference memory store enforces subject and purpose binding, allowed data classes, consent expiry, record TTL, forbidden classes, search scope, export, individual deletion, purpose revoke, subject deletion, and metadata-only audit. Assistant transcript/answer history is a separate process-memory UI feature with stricter default-off behavior.

### Privacy invariants

Raw audio, credentials, and secrets are forbidden. Rendering content does not authorize retention. Assistant history can be enabled only by a direct user action, is not persisted, and is destroyed on opt-out or process exit. Audit records identifiers, purpose, class, counts, and digests—not retained values.

### Production requirements

Persistent memory is unavailable until encrypted storage, per-subject keys, rotation, backup exclusion, migration, regional retention, export/delete UI, account deletion, abuse controls, subprocessor inventory, and witnessed deletion drills exist. Search and export authorization must remain subject- and purpose-bound.

<!-- module:codex-worker -->
## Codex specialist worker

### Responsibility and boundary

The worker validates a typed task envelope, fixes the executable and CLI shape, binds one task to one workspace below an operator root, permits only read-only or workspace-write sandboxes, limits prompt/runtime/output/workspace entries, filters environment variables, requires network isolation by default, streams bounded output, terminates the process group on timeout/limit, rejects symlink escape, and redacts credential-shaped output.

### Effect and release boundary

A worker may diagnose, plan, generate patches, and run tests. It has no BLE handle, permanent user or provider credential, release key, production deployment authority, approval authority, or self-merge authority. Patch custody and release decisions remain separate.

### Production requirements

Dry-run tests do not prove a deployed worker. Production requires an immutable image, short-lived workload identity, cgroup/resource quotas, read-only root, seccomp or equivalent isolation, controlled egress proxy, secret broker, task queue, artifact custody, tenant separation, compromise containment, observability, and independent review.

<!-- module:mcp-adapter -->
## MCP development adapter

### Responsibility and protocol

The dependency-free stdio adapter implements bounded JSON-RPC request framing, modern and legacy protocol negotiation, ping, tool discovery, and three deterministic read-only tools. `display.preview_card` renders a preview and never writes a physical G1. Unknown methods, tools, fields, malformed JSON, and oversized request lines fail with bounded errors.

### Authority boundary

The adapter contains no provider credential, OAuth handle, BLE handle, shell, account mutation, or hidden escalation path. Tool annotations declare read-only behavior, but deterministic server enforcement remains authoritative.

### Production change rule

Any future mutating MCP tool requires a new reviewed profile, exact schema, identity, capability registration, risk tier, lease, audit, receipt, reconciliation, and tests. A descriptive annotation alone is never sufficient authority.

<!-- module:qualification-release -->
## Qualification, evidence, and release gates

### Responsibility

This module evaluates physical trace scenarios, builds source SBOM and provenance, scans bounded complete Git history without emitting secrets, runs Android/iOS native sanitizers and PCM parity, evaluates source/product release bundles, and provides evidence templates and operational runbooks.

### Evidence custody

Source evidence must bind one unchanged commit and tree. The source artifact contains summary, gate result, history scan, native sanitizer report, provenance, release bundle, and SPDX SBOM. Every digest is re-read. A local run, parent commit, skipped job, cancelled workflow, PR prose, or self-written SHA is not E4.

Physical reports require exact app build, platform/device, G1 firmware/serial identity, scenario, trace, lab/operator identity, monotonic timestamps, correlation/effect IDs, and required faults. Synthetic traces remain evaluator tests only.

### Product gate

There is no override. Product release additionally requires protected-main evidence, independent latest-head review, physical Android/iOS reports, production KMS/HSM and attestation, provider receipts, credential incident closure, independent assurance, binary signing/SBOM/attestation, pilot telemetry, kill-switch, rollback, staged rollout, and store approval.

<!-- module:contracts-compatibility -->
## Contracts and compatibility

### Responsibility

`contracts/` contains composed runtime, control-plane, BLE, branch-protection, qualification, release, and history-scan contracts. `schemas/` contains Draft 2020-12 message and evidence schemas. Dart/Python/native implementations may be more restrictive but must not silently widen a contract.

### Versioning rule

A breaking field, authority identity, state transition, risk tier, data class, error meaning, or evidence rule requires an explicit contract revision and migration plan. Producers add optional fields before consumers require them. Unknown fields fail closed at security boundaries unless the version contract explicitly allows extension. Old journal or package formats require bounded offline migration, never silent reinterpretation.

### Change checklist

Update producer, consumer, schema, composed contract, deterministic fixtures, negative tests, module guide, Gap Ledger, Evidence Index, release template, and compatibility notes in one change. The metadata validator ensures referenced paths exist; semantic review remains independent.

<!-- module:repository-governance -->
## Repository governance, CI, and source authority

### Responsibility

The repository governance module defines source authority, CODEOWNERS, pull-request custody, required checks, read-only CI, dependency locks, history scanning, exact-head artifacts, review invalidation, and merge restrictions. The live PR head and tree—not prose—identify the candidate.

### CI matrix

The canonical workflow runs repository contracts and service tests, Flutter format/analyze/test, Android build/native tests, iOS simulator/native tests, native sanitizers, secret/boundary/history scan, and source evidence generation. Actions are commit-pinned, checkout credentials are not persisted, and workflow permissions are read-only.

`tools/validate_repository_metadata.py` verifies Gap Ledger references and module coverage independently of status prose. A closed row with a missing path fails. Blocked rows require a real source-side resume package and concrete unblock condition.

### Administrative boundary

The source contract cannot prove that GitHub applies it. All seven checks, strict mode, administrator enforcement, CODEOWNER and last-push approval, stale-review dismissal, conversation resolution, linear history, and no force-push/deletion must be observed through the GitHub API. The implementing identity never self-approves, bypasses, auto-merges, or self-merges.

<!-- module:native-dependencies -->
## Vendored native dependencies

### Responsibility

Vendored LC3 and RNNoise code is part of the mobile native attack surface and supply chain. The repository records source paths and builds the platform copies under ASAN/UBSAN, checks malformed input boundaries, and requires cross-platform PCM parity where applicable.

### Maintenance contract

Every vendored component requires supplier, license, version or truthful unknown-revision status, path, package identity, local patch inventory, build flags, sanitizer coverage, SBOM relationships, and upgrade procedure. A clean source scan does not replace legal review or vulnerability monitoring.

### Change checklist and external gates

Upgrades must preserve bitstream/PCM expectations, JNI/Objective-C ownership, allocation and error checks, platform build locks, sanitizer execution, and license notices. Production additionally requires supplier/version confirmation, independent license review, vulnerability response ownership, binary provenance, and release-candidate validation.
