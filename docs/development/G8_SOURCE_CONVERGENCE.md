# G8 Source Convergence

Canonical revision: `2026-08-31-g8`

This document defines the source-convergence boundary for the current Hepta Glasses candidate. The machine-readable state is `docs/PROJECT_STATE.json`; GitHub's live pull-request head is the exact source identity.

## Closed repository-actionable scope

The G8 source candidate closes the known repository-local blockers for:

- one response owner per connection generation, glasses side, and protocol command;
- bounded, serialized BLE writes and exclusive per-leg protocol transactions;
- truthful dual-leg delivery receipts and indeterminate-effect recovery;
- Android readiness sequencing and explicit Android voice capability limits;
- iOS framework-final speech handling with bounded failure semantics;
- durable, serialized audit-journal append with tamper detection and bounded storage;
- canonical Android, iOS, Dart, Kotlin, and JNI product identity;
- Android/iOS-only product platform scope and hardened mobile release defaults;
- a single read-only CI authority and exact-fingerprint history-scan acknowledgements;
- machine-readable Project State, Gap Ledger, Evidence Index, and release contracts.

Repository-local closure is demonstrated only when all seven required checks succeed on one unchanged pull-request head and the content-addressed source-evidence artifact validates without override.

## Dynamic evidence boundary

The repository never writes its own current commit SHA into the commit being attested. The authoritative exact identity is supplied by GitHub at runtime and bound into the CI artifact. Any push invalidates earlier exact-head CI and review.

E4 source evidence does not establish E5-E7 facts. Source code, simulators, unit tests, or digital twins cannot establish physical G1 qualification, deployed production controls, provider-side revocation, vendor firmware authority, independent assurance, signing, pilot, rollout, rollback, or store approval.

## Merge boundary

The implementing agent must not approve or merge its own work. The candidate becomes merge-eligible only after the unchanged head has all required checks successful, all review conversations resolved, and an eligible independent reviewer other than the last pusher approves it.

Product release remains blocked until the real external evidence gates in `docs/GAP_LEDGER.json` and the Product Release Bundle are satisfied.
