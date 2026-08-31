# G7 synthesis closure

This branch converges the stricter G4 native/mobile fixes with the G5/G6 audit,
SBOM, history, and release-evidence work.

## Evidence rule

Repository-actionable claims close only on one unchanged exact head after all
required repository, Flutter, Android, iOS, sanitizer, boundary, and source
evidence jobs pass. Physical-device, deployed-infrastructure, vendor,
administrative, independent-review, signing, pilot, and public-release gates
remain externally blocked until their evidence exists.

## Immediate closure targets

- formatter-clean Dart tree and executed analyzer/tests;
- LC3/RNNoise ASAN+UBSAN without suppressions and cross-platform PCM parity;
- current-tree secret cleanliness plus a redacted historical incident record;
- bounded, acknowledgement-checked bitmap transfer;
- fail-closed dual-leg readiness and non-overlapping heartbeat scheduling;
- valid Flutter history-list layout;
- canonical documentation and machine-readable gap status aligned to G7.
