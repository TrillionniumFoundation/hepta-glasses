# Hepta Glasses OS current state

Last updated: 2026-08-30
Canonical plan revision: `2026-08-30-g4`

## Authoritative review stack

The active source stack is:

1. PR #1 — AI-native distributed-OS foundation;
2. PR #9 — mobile execution-authority and native BLE hardening;
3. PR #10 — G4 exact-head reproducibility, concurrency, native safety, per-leg state, assistant lifecycle, and test-gate closure.

This file deliberately does not embed the current PR-head SHA. A commit cannot truthfully contain its own final SHA. The authoritative source identity is the exact commit and tree recorded by the successful GitHub Actions run and its `hepta-source-evidence-<sha>` artifact.

## Demonstrated repository state

The source tree now contains:

- a Flutter companion and deterministic mobile edge runtime for Even G1-class dual-BLE glasses;
- packet codecs, per-leg readiness, connection-generation fencing, late-response quarantine, replay-safe receipts, and a deterministic G1 digital twin;
- strict native LC3 frame validation on Android and iOS, bounded allocation, session-scoped decoder reset, and metadata-only audio diagnostics;
- a generation-fenced assistant lifecycle that waits for final ASR and reports completion only after the final display acknowledgement;
- a serialized, file-locked, hash-chained audit journal; recoverable tasks; exact-key in-flight de-duplication; journal-before-effect execution; and authoritative reconciliation contracts;
- a bounded device-effect scheduler and fail-closed timeout semantics where a write may already have occurred;
- a provider-neutral model gateway with no permanent provider credential in the mobile product bundle;
- reference control-plane identity, short-lived token, rotation, revocation, rate-limit, realtime, capability, Skill, Memory, qualification, governance, SBOM, provenance, and release-gate implementations;
- Flutter tests, Python tests, Android native unit tests, iOS XCTest, Android/iOS build gates, secret/boundary scans, and exact-head source evidence.

Android speech recognition is intentionally reported as unavailable until a real Android ASR adapter is configured; it is not represented as a successful no-op.

## Source truth

All repository-actionable gaps in `docs/GAP_LEDGER.yaml` are `CLOSED_SOURCE` or `CLOSED_VERIFIED`. Source closure means the implementation, contract, test, runbook, or validator exists and passes the exact-head source gate. It does not convert external evidence into source evidence.

## External gates that remain open

The following claims still require evidence that cannot be manufactured inside this repository:

- physical Android/iOS + Even G1 latency, packet-loss, power, thermal, disconnect, reconnect, and soak reports;
- deployed KMS/HSM identity, Android/Apple attestation, key rotation, revocation, lost-device, and recovery drills;
- active GitHub protection/ruleset verification for `main`;
- vendor-authorized firmware, bootloader, secure-boot, signing, OTA, and rollback authority;
- production model/realtime tenancy, OAuth registrations, external-system receipts, and timeout reconciliation;
- independent security/privacy/legal/accessibility review, release signing, pilot telemetry, kill-switch, staged rollout, rollback, and store approval.

These remain `BLOCKED_EXTERNAL`, `BLOCKED_ADMIN_SETTING`, or `BLOCKED_UPSTREAM`. A source CI pass must never be cited as proof that one of these gates is complete.

## Release truth

`tools/build_source_evidence.py` emits the exact-head SBOM, provenance, source release bundle, summary, and source gate result. `tools/evaluate_release_gate.py --mode product` additionally requires the external evidence above and has no override path.
