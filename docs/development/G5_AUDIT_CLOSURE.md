# G5 independent-audit source closure

Plan revision: `2026-08-30-g5`

G5 addresses repository-actionable gaps found after the G4 exact-head evidence package passed. It does not reinterpret E0–E4 source evidence as physical, deployed, administrative, upstream, independent-review, signing, pilot, or release evidence.

## Findings closed in source

### Durable audit truth

The prior JSONL journal serialized calls only inside one Dart object while documentation described it as file-locked. G5 adds a bounded cooperative cross-isolate/process marker, an exclusive OS file lock, same-handle reads/writes, UTF-8 and torn-tail rejection, entry/file limits, and tests for independent instances, separate isolates, tampering, torn records, and exhausted bounds. Product startup no longer silently substitutes a temporary directory when durable application support storage is unavailable.

The hash chain remains tamper-evident rather than tamper-proof. A production device must anchor checkpoints in independently protected storage or a remote control plane before the product release claim is made.

### Multi-ecosystem dependency evidence

The G4 SBOM parsed Dart packages but did not model the whole build/source surface. G5 adds Gradle plugins/dependencies/tooling, CocoaPods, CMake/build tools, a declared LC3/RNNoise vendored-source manifest, component content digests, PURLs, licenses, root-package relationships, file containment, and an inventory summary. This is still a source SBOM; signed binaries require their own binary SBOM and attestation.

### Credential-history handling

G5 adds a full-history scanner whose reports contain fingerprints rather than recovered values, a credential incident runbook, and an evidence template. Current-tree credential findings block source CI. Historical exposure remains an external incident-closure gate until provider revocation/rotation evidence and independent scope review exist.

### Native robustness and release configuration

G5 isolates the Android LC3 decoder core from JNI, adds deterministic boundary tests and bounded fuzzing under AddressSanitizer/UndefinedBehaviorSanitizer, aligns Android language/tool versions, makes warnings fatal in Flutter analysis, and adds Android release/lint plus iOS release-configuration build checks. Physical-device, power, thermal, long-soak, signed archive, and store evidence remain external.

## Exact-head rule

This document cannot contain the final commit SHA of its own tree. G5 becomes exact-head source evidence only when the GitHub Actions run on the PR head succeeds and the uploaded `hepta-source-evidence-<sha>` artifact binds the same commit, tree, `2026-08-30-g5` contracts version, multi-ecosystem inventory, credential-history digest, and release-gate result.

## External/admin/upstream truth retained

The following are not closed by this package: physical Android/iOS + G1 qualification, KMS/HSM and platform attestation, active protection of `main`, vendor firmware/bootloader/OTA authority, production realtime/OAuth/provider receipts, credential provider revocation, independent reviews, signed binary SBOM/attestation, pilot, kill-switch, rollback, and store approval.
