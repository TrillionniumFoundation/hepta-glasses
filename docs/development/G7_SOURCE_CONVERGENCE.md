# G7 source convergence package

Revision: `2026-08-31-g7`

## Purpose

This package converges the strongest source controls from the prior G4, G5, and
G6 lines and closes the repository-actionable blockers exposed by the red G5/G6
exact-head matrices. It is a source candidate, not a product-release claim.

## Repository-side closure

| Area | Closure |
|---|---|
| Authority | One read-only CI workflow; temporary self-modifying remediation workflows and stale exact-head marker files removed. |
| Canonical truth | Plan, Current State, Gap Ledger, Evidence Index, release gate, branch-protection contract, and evidence template share one revision. |
| Flutter/mobile | Formatter-clean target, fail-closed durable startup, valid history-list layout, safe busy-state cleanup, deterministic paging, model cancellation, and assistant cleanup. |
| BLE/device | Missing readiness fails closed, heartbeat cannot overlap, BMP transfer validates bounds/native acceptance/final ACK/CRC and does not blindly replay uncertain effects. |
| Runtime | Lease consumption occurs before the first asynchronous boundary; scheduler shutdown is bounded; model requests accept cancellation. |
| Control plane | Realtime ticket activation, capability idempotency, and single-use lease reservation are atomic under deterministic concurrent tests. |
| Skills/Codex | Skill admission hashes actual package bytes; Codex requires network isolation, rejects symlink escape, streams bounded output, kills the process group on limit/timeout, and redacts credential-shaped output. |
| Native | Signed-shift UB and deliberate RNNoise crash paths removed; JNI allocations/exceptions fail closed; Android/iOS LC3 and RNNoise run under ASAN/UBSAN with PCM parity. |
| Evidence | Complete bounded Git-object scan, zero-unscanned-blob requirement, deterministic multi-ecosystem SPDX, and content-verified source release gate. |

## Required unchanged-head checks

The candidate has E4 only after all of the following succeed on one unchanged
commit and tree:

- `repository-contracts`
- `flutter`
- `android-native`
- `ios-native`
- `native-sanitizers`
- `secret-and-boundary-scan`
- `source-evidence`

The source-evidence artifact must contain and bind the SBOM, provenance, history
scan, native sanitizer report, source bundle, summary, and gate result to that
exact head.

## Independent review rule

The implementing agent does not approve or merge this package. Any push makes a
prior review stale. An eligible independent reviewer must approve the unchanged
exact head after all required checks are terminal and successful.

## Explicit external non-closure

This package cannot close physical G1 qualification, production identity or
attestation, provider-side credential rotation, active main protection, vendor
firmware authority, production realtime/OAuth receipts, independent assurance,
release signing, pilot, rollout, rollback, or store approval. Those require the
E5–E7 evidence named in the Gap Ledger.
