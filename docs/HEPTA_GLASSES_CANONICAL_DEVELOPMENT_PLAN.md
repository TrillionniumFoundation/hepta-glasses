# Hepta Glasses canonical development plan

Revision: `2026-08-30-g5`
Supersedes: `2026-08-30-g4`, `2026-08-30-g3`, `2026-08-30-g2`, and `2026-08-30-g1`

## 1. Mission and product boundary

Convert the sanitized Even G1 companion demo into the deterministic mobile edge of a distributed AI-native glasses OS. The product boundary is the G1 device plane, mobile edge runtime, cloud control plane, capability adapters, and isolated Codex workers.

The repository does not contain vendor-authorized G1 firmware or bootloader source. “OS” therefore does not imply firmware ownership until secure-boot, signing, OTA, recovery, and rollback authority is contractually and technically available.

## 2. Non-negotiable invariants

1. Model, realtime model, MCP, Skill, notification, document, webpage, transcript, and Codex output are proposals, never final mutation authority.
2. The mobile bundle contains no permanent provider, OAuth, release-signing, account, KMS, or HSM credential.
3. Every mutation is schema-validated, policy-admitted, exact-argument bound, journaled before effect, idempotency-keyed, bounded, and reconciled when completion is uncertain.
4. Timeout, disconnect, process death, or missing acknowledgement is not proof of failure after a native or external write.
5. Decision leases are subject/device/task/action/argument/policy/time bound and single-use for mutations.
6. Untrusted content cannot grant authority or widen a capability.
7. Left and right glasses legs retain independent readiness, generation, and receipt truth; pair-level success requires both legs.
8. Connection, assistant, realtime, callback, and task generations fence stale asynchronous work.
9. Raw audio, credentials, secrets, and sensitive transcript content are not long-term Memory, audit, prompt, fixture, or evidence payload classes.
10. R4 capabilities, unrestricted shell, credential reads, firmware flashing, payment, and account mutation are unavailable in the consumer profile.
11. Durable mutation authority fails closed when protected local state cannot be established or verified.
12. Source/dependency evidence must cover every supported ecosystem and declared vendored component without guessing unproven upstream versions.
13. Credential-history reports contain only metadata and one-way fingerprints; clean source does not substitute for provider revocation.
14. Exact-head CI, simulators, sanitizer hosts, and digital twins are source evidence only; they cannot substitute for physical-device, deployed-infrastructure, administrative, upstream, independent-review, pilot, signing, or release evidence.
15. A source SBOM cannot substitute for a signed binary SBOM or artifact attestation.
16. The implementing agent does not self-approve or self-merge its own change.

## 3. Gate sequence

### G0 — canonical truth and governance

Maintain the product boundary, architecture, threat/privacy/capability models, canonical plan, current state, Gap Ledger, Evidence Index, schemas, CODEOWNERS, CI, third-party inventory, and branch-protection contract.

Source exit: validators pass and no actionable source gap is `OPEN`. Product exit: GitHub verifies the canonical `main` protection contract and post-merge exact-head checks.

### G1 — deterministic device substrate

Maintain protocol codecs, native transport adapters, independent per-leg readiness, connection generations, bounded write queues, exact response correlation, dual-leg receipts, retry safety, late-response quarantine, reconciliation, and deterministic fault injection.

Source exit: malformed packets fail closed; an uncertain write is never blindly replayed; partial pair completion is explicit. Product exit: physical Android/iOS G1 qualification passes.

### G2 — edge execution authority

Maintain durable tasks, bounded serialized hash-chained audit, cross-instance/process exclusion, journal-before-effect execution, exact-key in-flight de-duplication, bounded physical-effect scheduling, policy, exact leases, recovery, receipts, deadlines, cancellation, and reconciliation.

Source exit: corrupt/torn journals, duplicate concurrent requests, stale generations, argument drift, expired/consumed leases, unknown tools, storage failure, and crash windows fail closed.

### G3 — identity and cloud control

Maintain reference device registration, attestation-verifier interfaces, key-ID signing, short-lived subject/device/session-bound tokens, rotation, rate limits, revocation, recovery contracts, and deployment runbooks.

Source exit: deterministic identity tests pass. Product exit: deployed KMS/HSM, platform attestation, rotation, revoke, lost-device, and recovery drills pass.

### G4 — realtime and assistant lifecycle

Maintain one-time realtime bootstrap, bounded scopes/provider profiles, privacy indicators, cancellation, barge-in fencing, final-ASR waiting, model cancellation boundaries, and delivery-truth state transitions.

Source exit: replay, stale generation, unavailable ASR, late transcript, and unacknowledged final display fail closed. Product exit: physical latency, loss, battery, thermal, cancellation, and barge-in thresholds pass.

### G5 — capability tool OS

Maintain opaque OAuth handles, typed adapters, schema validation, untrusted-content separation, exact approvals, idempotency, external receipts, and authoritative reconciliation.

Source exit: negative and deterministic adapter tests pass. Product exit: real provider/OAuth adapters return authoritative receipts and reconcile timeouts.

### G6 — Codex specialist lane

Maintain one-task/one-workspace/one-identity workers, bounded runtime/output/network, no BLE or production credentials, patch/test custody, maintainer review, and no self-merge.

Source exit: policy and launcher tests pass. Product exit: deployed isolation, short-lived identity, egress, secret-boundary, and compromise-containment exercises pass.

### G7 — Skills and Memory

Maintain signed manifests, trust roots, package digests, domain/capability/data-class admission, upgrade re-consent, revoke, purpose-bound Memory, TTL, export, and deletion.

Source exit: tampering, R4 admission, missing consent, unauthorized domain, and revoked package fail closed. Product exit: production signing roots, encrypted storage, independent review, and deletion drills pass.

### G8 — qualification, pilot, and release

Maintain physical trace evaluators, fault matrices, Android/iOS/native tests, multi-ecosystem source SBOM/provenance, credential-history evidence, source/product release gates, governance automation, signing/review templates, rollout, kill-switch, and rollback runbooks.

Source exit: exact-head repository, Flutter, Android, iOS, native-sanitizer, boundary/history, and source-evidence checks pass. Product exit: a signed product release bundle with binary SBOM and artifact attestation passes without overrides.

## 4. Evidence levels

- **E0 — Contract evidence:** plans, ADRs, schemas, policies, inventories, runbooks, and machine-readable ledgers.
- **E1 — Static source evidence:** formatting, compilation, strict static analysis, boundary/history scans, dependency inventory, and deterministic validators.
- **E2 — Deterministic test evidence:** unit, negative, property, replay, crash-window, cross-isolate, sanitizer, bounded-fuzz, and digital-twin tests.
- **E3 — Platform build/test evidence:** Android native tests/lint/release configuration, iOS XCTest/simulator release configuration, and reproducible dependency locks.
- **E4 — Exact-head CI evidence:** successful required checks plus content-addressed source SBOM, provenance, credential-history summary, and source-gate artifact bound to one commit and tree.
- **E5 — Physical/deployed evidence:** real device traces, deployed services, KMS/HSM, attestation, OAuth/provider receipts, provider revocation receipts, and operational telemetry.
- **E6 — Independent assurance:** external security, privacy, legal, accessibility, safety, supply-chain, and vendor reviews plus witnessed drills.
- **E7 — Release evidence:** signed binaries, binary SBOM, artifact attestation, pilot outcomes, staged rollout, kill-switch, rollback, store approval, and a passing product release bundle.

Evidence cannot be promoted by renaming it. E0–E4 never close a gate that explicitly requires E5–E7.

## 5. G5 closure order

1. Correct durable-audit claims with cross-instance/process exclusion, OS locking, bounded storage, torn-tail rejection, and fail-closed startup.
2. Expand source dependency evidence across Dart, Gradle, CocoaPods, build tools, and vendored native source.
3. Add full-history credential fingerprinting while preserving provider revocation and scope review as external truth.
4. Isolate native decoder boundaries and execute deterministic sanitizer/fuzz checks.
5. Make warnings fatal and prove Android/iOS release configurations without substituting unsigned builds for signing evidence.
6. Bind all source checks, inventory, history digest, provenance, and plan revision to the exact PR head.
7. Retain active `main` protection, independent merge, post-merge evidence, physical/deployed/vendor review, signed binaries, pilot, and release as explicit external/admin/upstream gates.
