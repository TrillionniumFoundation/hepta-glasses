# Hepta Glasses canonical development plan

Revision: `2026-08-31-g7`
Supersedes: `2026-08-31-g5`, `2026-08-30-g4`, `2026-08-30-g3`, `2026-08-30-g2`, and `2026-08-30-g1`

## 1. Mission and product boundary

Convert the imported Even G1 companion demo into the deterministic mobile edge of a distributed AI-native glasses OS. The product boundary is the G1 device plane, the mobile edge runtime, a cloud control plane, capability adapters, and isolated Codex workers.

The repository does not contain vendor G1 firmware or bootloader source. “OS” therefore does not imply firmware ownership until vendor-authorized firmware, secure-boot, signing, OTA, recovery, and rollback access exists.

## 2. Non-negotiable invariants

1. Model, realtime model, MCP, Skill, and Codex output are proposals, never final mutation authority.
2. The mobile bundle contains no permanent provider, OAuth, release-signing, or account credential.
3. Every mutation is schema-validated, policy-admitted, exact-argument bound, journaled before effect, idempotency-keyed, and reconciled when completion is uncertain.
4. Timeout, disconnect, process death, or missing acknowledgement is not proof of failure after a native write.
5. Decision leases are subject/device/task/action/argument/policy/time bound and single-use for mutations; a lease is atomically consumed before the first asynchronous effect boundary.
6. Untrusted notification, document, webpage, transcript, model, or tool content cannot grant authority.
7. Left and right glasses legs retain independent readiness and receipts; pair-level success requires both legs.
8. Connection, assistant, realtime, callback, paging, and cancellation generations fence stale asynchronous work.
9. Raw audio, credentials, secrets, and sensitive transcript content are not long-term Memory or audit payload classes.
10. R4 capabilities, unrestricted shell, credential reads, firmware flashing, payment, and account mutation are unavailable in the consumer profile.
11. Exact-head CI and digital twins are source evidence only; they cannot substitute for physical-device, deployed-infrastructure, independent-review, pilot, signing, or release evidence.
12. A clean worktree is not a clean Git history. Every fetched ref and every bounded blob must pass the redacted history gate; unscanned blobs fail closed.
13. Development servers fail closed when authentication or isolation prerequisites are absent.
14. The implementing agent does not self-approve or self-merge its own change.

## 3. Gate sequence

### G0 — canonical truth and governance

Maintain the product boundary, architecture, threat/privacy/capability models, canonical plan, current state, Gap Ledger, Evidence Index, schemas, CODEOWNERS, a single read-only CI workflow, and the branch-protection contract.

Source exit: validators pass, all canonical revisions agree, and no actionable source gap is `OPEN`. Product exit: GitHub verifies the canonical `main` protection contract.

### G1 — deterministic device substrate

Maintain protocol codecs, native transport adapters, independent per-leg readiness, connection generations, bounded write queues, exact response correlation, dual-leg receipts, retry safety, late-response quarantine, reconciliation, and deterministic fault injection.

Source exit: malformed packets fail closed; an uncertain write is never blindly replayed; partial pair completion is explicit; bulk BMP transfer validates every native acceptance and terminal response. Product exit: physical Android/iOS G1 qualification passes.

### G2 — edge execution authority

Maintain durable tasks, serialized hash-chained audit, exact-key in-flight de-duplication, bounded physical-effect scheduling, policy, exact leases, Tool Gateway recovery, journal-before-effect execution, receipts, deadlines, cancellation, and reconciliation.

Source exit: corrupt journals, duplicate concurrent requests, stale generations, argument drift, expired/consumed leases, unknown tools, crash windows, cancellation races, and blocked shutdowns fail closed.

### G3 — identity and cloud control

Maintain reference device registration, attestation-verifier interfaces, key-ID signing, short-lived subject/device/session-bound tokens, rotation, rate limits, revocation, recovery contracts, and deployment runbooks.

Source exit: deterministic identity tests pass. Product exit: deployed KMS/HSM, platform attestation, rotation, revoke, lost-device, and recovery drills pass.

### G4 — realtime and assistant lifecycle

Maintain one-time realtime bootstrap, bounded scopes/provider profiles, privacy indicators, cancellation, barge-in fencing, final-ASR waiting, model cancellation boundaries, and delivery-truth state transitions.

Source exit: replay, concurrent ticket consumption, stale generation, unavailable ASR, late transcript, overlapping paging, and unacknowledged final display fail closed. Product exit: physical latency, loss, battery, thermal, cancellation, and barge-in thresholds pass.

### G5 — capability tool OS

Maintain opaque OAuth handles, typed adapters, schema validation, untrusted-content separation, exact approvals, atomic idempotency, external receipts, and authoritative reconciliation.

Source exit: concurrent duplicate execution, lease reuse, Prompt Injection, malformed arguments, and uncertain completion fail closed under deterministic tests. Product exit: real provider/OAuth adapters return authoritative receipts and reconcile timeouts.

### G6 — Codex specialist lane

Maintain one-task/one-workspace/one-identity workers, bounded runtime/output/network/filesystem, no BLE or production credentials, patch/test custody, maintainer review, and no self-merge.

Source exit: network isolation is mandatory, symlink escape and output amplification fail closed, secrets are redacted, and launcher tests pass. Product exit: deployed isolation, short-lived identity, egress, secret-boundary, and compromise-containment exercises pass.

### G7 — Skills and Memory

Maintain signed manifests, trust roots, package-byte digests, domain/capability/data-class admission, upgrade re-consent, revoke, purpose-bound Memory, TTL, export, and deletion.

Source exit: package substitution, tampering, R4 admission, missing consent, unauthorized domain, and revoked package fail closed. Product exit: production asymmetric signing roots, encrypted storage, independent review, and deletion drills pass.

### G8 — qualification, pilot, and release

Maintain physical trace evaluators, fault matrices, Android/iOS native tests, exact-head source SBOM/provenance, redacted complete-history scanning, native sanitizers, source/product release gates, governance automation, signing/review templates, rollout, kill-switch, and rollback runbooks.

Source exit: exact-head repository, Flutter, Android, iOS, native-sanitizer, boundary/history, and source-evidence checks pass on one unchanged commit. Product exit: a signed product release bundle passes without overrides.

## 4. Evidence levels

- **E0 — Contract evidence:** plans, ADRs, schemas, policies, runbooks, and machine-readable ledgers.
- **E1 — Static source evidence:** formatting, compilation, static analysis, boundary scans, and deterministic validators.
- **E2 — Deterministic test evidence:** unit, negative, concurrency, property, replay, crash-window, and digital-twin tests.
- **E3 — Platform build/test evidence:** Android native unit tests, iOS XCTest, simulator builds, native sanitizers, and reproducible dependency locks.
- **E4 — Exact-head CI evidence:** a successful CI run and content-addressed SBOM/provenance/history/native/source-gate artifact bound to one unchanged commit and tree.
- **E5 — Physical/deployed evidence:** real device traces, deployed services, KMS/HSM, attestation, OAuth/provider receipts, credential-rotation records, and operational telemetry.
- **E6 — Independent assurance:** external security, privacy, legal, accessibility, safety, and vendor reviews plus witnessed drills.
- **E7 — Release evidence:** signed artifacts, verifiable binary attestations, pilot outcomes, staged rollout, kill-switch, rollback, store approval, and a passing product release bundle.

Evidence cannot be promoted by renaming it. E0–E4 never close a gate that explicitly requires E5–E7.

## 5. Revision g7 source-convergence order

1. Preserve the strongest invariant from the G4, G5, and G6 branches without force-replacing reviewed history.
2. Remove temporary self-modifying remediation workflows and stale exact-head marker files; retain one read-only CI authority.
3. Close Flutter formatting, UI crash, BLE/BMP, assistant cancellation, lease, scheduler, concurrency, package-integrity, worker-isolation, and native UB blockers.
4. Make the history gate redacted and complete: findings or unscanned bounded objects fail the source gate.
5. Keep historical credential rotation/revocation, physical devices, production infrastructure, repository administration, vendor firmware, independent assurance, signing, pilot, and release explicitly external.
6. Run the complete matrix on one unchanged exact head, generate content-addressed evidence, and obtain independent review bound to that head.
7. Merge only through the protected review path. The implementing agent never self-approves, bypasses, or self-merges.
