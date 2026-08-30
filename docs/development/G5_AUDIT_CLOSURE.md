# G5 independent-audit source closure

Revision: `2026-08-31-g5`

This package closes repository-actionable defects discovered after the G4
candidate. It does not claim physical-device, deployed-infrastructure,
independent-assurance, signing, pilot, or public-release evidence.

## Closure map

- `HG-0035`: OS advisory lock, atomic checkpoint, crash repair, cross-instance
  tests, torn-tail rejection, and no temporary-storage fallback.
- `HG-0036`: deterministic SPDX packages and relationships for Pub, Gradle,
  CocoaPods, and vendored native code.
- `HG-0037`: every fetched ref and deduplicated Git blob is scanned; possible
  secrets are represented only by SHA-256 fingerprints.
- `HG-0038`: source-gate evaluation recomputes artifact digests and reads the
  history/native report content.
- `HG-0039`: machine-readable LC3/RNNoise supplier, license, path, PURL, and
  unknown-revision truth.
- `HG-0040`: both platform LC3 copies and RNNoise run under ASAN/UBSAN; identical
  inputs must produce identical Android/iOS PCM digests.

## Exact-head rule

Closure becomes E4 only after the final G5 head completes all required jobs and
its downloaded `hepta-source-evidence-<sha>` artifact is independently checked.
A passing parent commit or the source-export workflow is not sufficient.

## External handoff

`HG-0015` through `HG-0020` and `HG-0041` through `HG-0043` remain blocked until
real E5-E7 evidence is supplied. No source-only override exists.
