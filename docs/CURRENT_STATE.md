# Hepta Glasses OS current state

Last updated: 2026-08-31
Canonical plan revision: `2026-08-31-g7`

## Authoritative review stack

G5 is an independent-audit closure stacked on the exact G4 source candidate. The
authoritative identity is the exact commit and tree recorded by a successful CI
run and its `hepta-source-evidence-<sha>` artifact. A PR description is not
evidence and this file deliberately does not claim its own future final SHA.

## Demonstrated source state

The source tree contains the G4 deterministic device/runtime foundation plus:

- an OS-file-locked, hash-chained JSONL audit journal with atomic head
  checkpoints, cross-instance serialization, torn-tail rejection, and recovery
  after journal flush but before checkpoint replacement;
- fail-closed durable-storage startup with no silent system-temporary fallback;
- a deterministic SPDX 2.3 SBOM spanning Dart/Pub, Android/Gradle,
  iOS/CocoaPods, and vendored native components;
- a redacted all-fetched-ref Git history scanner;
- ASAN/UBSAN execution of both vendored LC3 copies and RNNoise, with Android/iOS
  PCM parity required;
- source release evaluation that recomputes evidence-file digests and verifies
  report contents rather than accepting digest-shaped strings;
- a CI policy where Dart warnings are fatal.

## Source truth

Repository-actionable G5 gaps are closed only when the exact-head source gate
passes. Local tests, a prior G4 artifact, or a source-export workflow do not
prove the G5 head.

## External gates that remain open

The following still require evidence that cannot be manufactured in this
repository:

- physical Android/iOS + Even G1 qualification, power, thermal, reconnect, and
  soak reports;
- deployed KMS/HSM identity, Android/Apple attestation, rotation, revocation,
  lost-device, and recovery drills;
- active and API-verified protection/rulesets for `main`;
- vendor-authorized firmware, bootloader, secure-boot, signing, OTA, and
  rollback authority;
- production model/realtime tenancy, OAuth registrations, authoritative
  external receipts, and timeout reconciliation;
- independent security, privacy, legal, and accessibility review;
- Android/iOS release signing, verifiable binary attestation, pilot telemetry,
  kill-switch, staged rollout, rollback, and store approval;
- provider-side rotation or revocation evidence for any historically exposed
  credential.

These remain `BLOCKED_EXTERNAL`, `BLOCKED_ADMIN_SETTING`, or
`BLOCKED_UPSTREAM`. E0-E4 never close E5-E7.
