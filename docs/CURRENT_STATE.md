# Hepta Glasses OS current state

Last updated: 2026-09-01
Canonical plan revision: `2026-09-01-g8`

## Authoritative source candidate

Revision g8 converges the strongest repository-side controls from the prior G4–G7 lines and closes the repository-actionable BLE authority defects identified during independent review. Its authoritative identity is not this prose: E4 exists only when the unchanged live PR head and tree complete every required CI job and the resulting `hepta-source-evidence-<sha>` artifact passes content verification. A local run, source export, parent-commit result, PR description, manually written SHA, or cancelled workflow is not exact-head evidence.

## Demonstrated repository-side state

The source candidate contains:

- independent left/right BLE readiness, generation fencing, late-response quarantine, non-overlapping heartbeat scheduling, strict response shapes, and no blind replay after a native write may have occurred;
- iOS callback ownership bound to an immutable `(peripheral identity, side, generation, attempt nonce)` token, with a retired-peripheral barrier preventing a cancelled CBPeripheral from being reassigned before its terminal callback is consumed;
- public BLE transport idempotency scoped to `(pair identity, generation, side, caller key, payload digest)`, with the captured pair and generation asserted again by Flutter and both native write paths;
- one-leg disconnect handling that fails or quarantines only the affected leg's pending owners and never clears an uncertain-write quarantine on the surviving leg;
- hostile regressions covering generation-N callbacks after generation N+1, unknown peripheral ownership, cross-side/cross-generation/cross-pair key reuse, payload drift, and opposite-leg disconnect isolation;
- a bounded BMP transfer state machine that rejects invalid size/sequence, native write refusal, malformed finish replies, and malformed CRC replies;
- fail-closed durable startup, process-wide and OS-file serialization, full hash-chain authentication before every append, bounded v2 checkpoints, torn-tail rejection, and bounded scheduler shutdown;
- atomic single-use lease consumption, in-flight idempotency coalescing, cancellation-aware model requests, and deterministic assistant/text paging;
- assistant transcript/answer history that is disabled by default, enabled only by a direct user control, retained only in process memory, and deleted immediately on opt-out;
- atomic realtime ticket activation and capability execution under concurrent requests;
- package-byte verification for Skills and a Codex worker that requires network isolation, bounds streamed output, rejects workspace escape, and redacts credential-shaped output;
- ASAN/UBSAN execution of Android/iOS LC3 plus RNNoise and required cross-platform PCM parity;
- deterministic Pub/Gradle/CocoaPods/vendored-native SPDX evidence, redacted all-ref history scanning, and source/product release gates that re-read the evidence content;
- one read-only CI workflow and no retained connector probe files.

Repository contracts and deterministic tests can establish E1–E3 for a working candidate. E4 is determined only by GitHub's successful exact-head run and its content-addressed evidence artifact; any later source push invalidates the prior E4 record until the full matrix succeeds again.

## Machine-readable current boundaries

`PROJECT_STATE.json` defines source authority and external blockers without self-attesting a SHA. `PLATFORM_CAPABILITIES.json` records that Android voice ASR is unavailable fail-closed and that neither platform has physical-G1 attestation. `contracts/g1-ble-protocol-v1.json` is the byte-level and authority source contract; vendor and physical evidence remain authoritative for firmware facts.

## Truthful platform boundary

The Android application builds the G1 transport and LC3 path, but no production Android PCM-to-ASR provider is configured. Android voice-assistant activation therefore fails closed rather than pretending to record or transcribe. Full cross-platform voice qualification remains part of the physical/provider gate.

## Repository governance observation

The public branch endpoint reports `main` as protected, but the observable required-check set contains only four of the seven canonical contexts. The detailed protection endpoint is not readable by the current integration, so review, administrator enforcement, last-push approval, conversation resolution, linear-history, force-push, and deletion settings cannot all be verified from this source package. The canonical protection gap therefore remains `BLOCKED_ADMIN_SETTING`; `protected=true` alone is not treated as closure.

## External and administrative gates still open

The following evidence cannot be manufactured by repository code and remains `BLOCKED_EXTERNAL`, `BLOCKED_ADMIN_SETTING`, or `BLOCKED_UPSTREAM`:

- physical Android/iOS + Even G1 protocol, loss, reconnect, latency, power, thermal, cancellation, barge-in, and soak reports;
- deployed KMS/HSM identity, Android/Apple attestation, rotation, revoke, lost-device, and recovery drills;
- provider-side revocation and rotation proof for the historically exposed credential;
- active, API-verified canonical protection/rulesets for `main`, including all seven required contexts and review controls;
- vendor-authorized firmware, bootloader, secure boot, signing, OTA, recovery, and rollback authority;
- production model/realtime tenancy, OAuth registrations, authoritative external receipts, and timeout reconciliation;
- an independent approving review bound to the unchanged exact source head;
- independent security, privacy, legal, accessibility, and safety review;
- Android/iOS release signing, binary SBOM/attestation, pilot telemetry, kill-switch, staged rollout, rollback, and store approval.

E0–E4 never close E5–E7. The product release gate remains fail-closed until all required external evidence is attached and independently verified.
