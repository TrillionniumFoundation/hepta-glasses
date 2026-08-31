# G5 independent-audit source package

Revision: `2026-08-31-g5`

This historical package introduced repository-side audit, supply-chain, history,
native-sanitizer, and evidence-gate controls after the G4 candidate. Its G5/G6
exact-head runs remained red, so the package by itself is not E4 evidence. The
controls and their subsequent repairs are converged by revision g7.

## Introduced controls

- process-safe audit locking, atomic checkpoints, crash repair, torn-tail
  rejection, and fail-closed durable startup;
- deterministic SPDX packages and relationships for Pub, Gradle, CocoaPods, and
  vendored native code;
- redacted all-ref Git history scanning;
- release evaluation that recomputes artifact digests and reads history/native
  report content;
- machine-readable LC3/RNNoise supplier, license, path, PURL, and
  unknown-revision truth;
- ASAN/UBSAN execution of both platform LC3 copies and RNNoise with PCM parity.

## Superseding closure

`docs/development/G7_SOURCE_CONVERGENCE.md` closes the source defects exposed by
the red G5/G6 matrices, including formatter drift, sanitizer execution/UB,
incomplete history scanning, mobile correctness, concurrency, package
integrity, and worker isolation.

## Evidence ceiling

Neither this package nor g7 can claim physical devices, deployed
infrastructure, provider-side credential rotation, repository administration,
vendor firmware, independent assurance, signing, pilot, or release. Those
remain external E5–E7 gates.
