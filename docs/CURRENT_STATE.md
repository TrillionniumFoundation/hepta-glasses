# Hepta Glasses OS current state

Last updated: 2026-09-02
Canonical plan revision: `2026-09-01-g8`

## Authoritative source candidate

Revision g8 converges the strongest repository-side controls from the prior G4–G7 lines and closes the repository-actionable defects identified during independent and metadata review. Its authoritative identity is not this prose: E4 exists only when the unchanged live PR head and tree complete every required CI job and the resulting `hepta-source-evidence-<sha>` artifact passes content verification. A local run, source export, parent-commit result, PR description, manually written SHA, cancelled workflow, or workflow with an empty job set is not exact-head evidence.

The current branch has changed after the last successful source artifact. Consequently, prior E4 artifacts remain historical evidence only and do not attest the current head. The exact-head source gate must be regenerated after the source tree is frozen.

## Demonstrated repository-side state

The source candidate contains:

- independent left/right BLE readiness, generation fencing, late-response quarantine, non-overlapping heartbeat scheduling, strict response shapes, and no blind replay after a native write may have occurred;
- iOS callback ownership bound to an immutable `(peripheral identity, side, generation, attempt nonce)` token, with a retired-peripheral barrier preventing a cancelled CBPeripheral from being reassigned before its terminal callback is consumed;
- public BLE transport idempotency scoped to `(pair identity, generation, side, caller key, payload digest)`, with the captured pair and generation asserted again by Flutter and both native write paths;
- one-leg disconnect handling that fails or quarantines only the affected leg's pending owners and never clears an uncertain-write quarantine on the surviving leg;
- hostile regressions covering generation-N callbacks after generation N+1, unknown peripheral ownership, unscoped native responses, cross-side/cross-generation/cross-pair key reuse, payload drift, and opposite-leg disconnect isolation;
- a digital twin whose authority domain now matches the production transport across pair, positive generation, side, caller key, and payload digest, while remaining E2-only synthetic evidence;
- a bounded BMP transfer state machine that rejects invalid size/sequence, native write refusal, malformed finish replies, and malformed CRC replies;
- a single mobile composition root in `lib/bootstrap/hepta_bootstrap.dart`; durable runtime or platform-authenticator failure leaves all assistant and device actions disabled;
- a production mobile dependency graph with no development/test lease provider or forgeable authority define; Android release APK and unsigned iOS device-target release AOT binaries are inspected for forbidden authority material;
- process-wide and OS-file audit serialization, full-chain verification on startup/read/explicit verify and whenever append trust metadata drifts, a platform-authenticated bounded-tail append fast path, v3 checkpoints, torn-tail rejection, and bounded scheduler shutdown;
- atomic single-use lease consumption, in-flight idempotency coalescing, cancellation-aware model requests, microphone and heartbeat retry-safety regressions, and deterministic assistant/text paging;
- assistant transcript/answer history that is disabled by default, enabled only by a direct user control, retained only in process memory, and deleted immediately on opt-out;
- atomic realtime ticket activation and capability execution under concurrent requests;
- package-byte verification for Skills and a Codex worker that requires network isolation, bounds streamed output, rejects workspace escape, and redacts credential-shaped output;
- ASAN/UBSAN execution of Android/iOS LC3 plus RNNoise and required cross-platform PCM parity;
- deterministic Pub/Gradle/CocoaPods/vendored-native SPDX evidence, redacted all-ref history scanning, and source/product release gates that re-read the evidence content;
- one read-only CI workflow; PR branches execute one pull_request matrix, main alone uses push, and no retained connector probe files;
- a v6 Gap Ledger with 72 rows: 60 source-closed, 12 externally/admin/upstream blocked, and zero repository-actionable OPEN rows; every evidence and resume reference is checked for existence;
- a 22-module machine-readable ownership/test/contract/documentation registry and a detailed technical development guide, both enforced by `tools/validate_repository_metadata.py` in CI.

Repository contracts and deterministic tests can establish E1–E3 for a working candidate. E4 is determined only by GitHub's successful exact-head run and its content-addressed evidence artifact; any later source push invalidates the prior E4 record until the full matrix succeeds again.

## Audit integrity truth

`JsonlAuditJournal` always verifies the complete chain during initialization, `readAll`, and explicit `verify`. Ordinary append may use a bounded authenticated-tail path only when the process-trusted checkpoint, platform HMAC, file length, filesystem modification/change timestamps, and terminal record all agree. A missing cache entry, metadata change, stale or legacy checkpoint, invalid MAC, or anchor mismatch triggers complete verification before append.

This design does **not** claim that every ordinary append rescans every historical byte. An attacker able to alter the journal and perfectly restore all observed filesystem metadata could defer middle-record detection until the next full verification, although the attacker cannot forge or advance the platform-authenticated checkpoint without the device key. Production assurance must define periodic full verification and may add immutable segments, remote/WORM root anchoring, or a trusted monotonic anchor.

## Machine-readable current boundaries

`PROJECT_STATE.json` defines source authority and external blockers without self-attesting a SHA. `MODULES.json` defines module owners, source roots, detailed documentation, tests, contracts, lifecycle, and external gates. `PLATFORM_CAPABILITIES.json` records that Android voice ASR is unavailable fail-closed and that neither platform has physical-G1 attestation. `contracts/g1-ble-protocol-v1.json` is the byte-level and authority source contract; vendor and physical evidence remain authoritative for firmware facts.

Legacy social-post, mobile OCR, and a separate `hepta_dashboard` are not current capabilities. Their historical Gap Ledger rows are closed only as `REMOVED_FROM_PRODUCT_BOUNDARY`, not as implementations. Reintroduction requires a new module, risk/privacy design, contracts, tests, and evidence.

## Truthful platform boundary

The Android application builds the G1 transport and LC3 path, but no production Android PCM-to-ASR provider is configured. Android voice-assistant activation therefore fails closed rather than pretending to record or transcribe. Full cross-platform voice qualification remains part of the physical/provider gate.

## Repository governance observation

The public branch endpoint reports `main` as protected, but the previously observable required-check set contained only four of the seven canonical contexts. The detailed protection endpoint was not readable by the current integration, so review, administrator enforcement, last-push approval, conversation resolution, linear-history, force-push, and deletion settings could not all be verified from the source package. The canonical protection gap therefore remains `BLOCKED_ADMIN_SETTING`; `protected=true` alone is not treated as closure.

The PR must remain unmergeable until the final unchanged head has seven non-empty successful jobs, a content-verified artifact, resolved conversations, an eligible latest-head approval, and API evidence matching the complete protection contract. The implementing identity does not self-approve, enable auto-merge, bypass protection, or self-merge.

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
