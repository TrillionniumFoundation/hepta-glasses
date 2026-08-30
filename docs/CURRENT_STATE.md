# Hepta Glasses OS current state

Last updated: 2026-08-30
Canonical plan revision: `2026-08-30-g5`

## Authoritative review stack

The active source line is the existing stacked review branch ending in PR #10. G5 is an additional package on that same branch and PR. The implementing agent must not approve or merge its own change. The final source identity is the exact commit and tree recorded by a successful GitHub Actions run and its content-addressed evidence artifact; a commit cannot truthfully embed its own final SHA.

## Demonstrated source state

The candidate tree contains:

- a Flutter companion and deterministic mobile edge runtime for Even G1-class dual-BLE glasses;
- protocol codecs, independent per-leg readiness, connection/assistant generations, exact response matching, late-response quarantine, degraded receipts, and a deterministic G1 digital twin;
- Android/iOS LC3 validation plus an isolated Android decoder core, bounded allocation, deterministic host tests, sanitizer checks, and bounded fuzzing;
- a generation-fenced assistant lifecycle that waits for final ASR and reports completion only after final display acknowledgement;
- a bounded, hash-chained JSONL audit journal with cross-instance/process coordination, an OS file lock, same-handle I/O, torn-tail rejection, and fail-closed durable-storage startup;
- recoverable tasks, exact-key in-flight de-duplication, journal-before-effect execution, bounded physical-effect scheduling, timeout indeterminacy, terminal receipt protection, and authoritative reconciliation contracts;
- a provider-neutral model gateway with no permanent provider credential in the mobile product bundle;
- reference identity, short-lived token, rotation, revocation, rate-limit, realtime, capability, Skill, Memory, qualification, governance, SBOM, provenance, and release-gate services;
- multi-ecosystem source inventory for Dart, Gradle, CocoaPods, build tools, and declared vendored LC3/RNNoise source;
- full-history credential-fingerprint scanning, an incident runbook, and a redacted closure template;
- exact-head Flutter, Python, Android, iOS, native-sanitizer, boundary/history, and source-evidence gates.

Android speech recognition remains intentionally unavailable until a real Android ASR adapter is configured; it is not represented as a successful no-op.

## Source truth

All repository-actionable G5 entries are represented as `CLOSED_SOURCE` with code, contract, test, validator, or runbook evidence. They become exact-head E4 evidence only after the current PR head passes CI and produces a matching artifact. No `OPEN` repository-actionable entry is permitted by the source validator.

Source closure does not close external/admin/upstream claims. The source SBOM is not a binary SBOM; a history scan is not a provider revocation receipt; simulator/native host tests are not physical-device qualification; and a branch-protection JSON file is not active GitHub enforcement.

## Gates that remain blocked by real-world evidence

- physical Android/iOS + Even G1 latency, packet-loss, power, thermal, disconnect/reconnect, and soak reports;
- deployed KMS/HSM identity, Android/Apple attestation, rotation, revocation, lost-device, and recovery drills;
- active GitHub protection/ruleset verification for `main` and an independently reviewed merge followed by post-merge exact-head evidence;
- vendor-authorized firmware, bootloader, secure boot, signing, OTA, recovery, and rollback authority;
- production model/realtime tenancy, OAuth registrations, authoritative external receipts, and timeout reconciliation;
- provider-side revocation/rotation evidence for historical credential exposure plus independent scope review;
- independent security, privacy, legal, accessibility, safety, and supply-chain review;
- signed Android/iOS binaries, binary SBOM, artifact attestation, pilot telemetry, kill-switch, staged rollout, rollback, and store approval.

These remain `BLOCKED_EXTERNAL`, `BLOCKED_ADMIN_SETTING`, or `BLOCKED_UPSTREAM`. They must not be renamed or promoted without their required E5–E7 evidence.

## Release truth

`tools/build_source_evidence.py` emits an exact-head multi-ecosystem source SBOM, provenance, credential-history summary, source release bundle, summary, and source-gate result. `tools/evaluate_release_gate.py --mode product` additionally requires the external evidence above and has no override path.
