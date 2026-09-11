# G8 source-integrity, BLE authority, privacy, and documentation remediation

Status: repository-side implementation record. It is not independent approval, physical-device qualification, deployed-infrastructure evidence, or product-release evidence.

Canonical revision: `2026-09-01-g8`

## Closed source defects

### Durable audit and evidence integrity

- restored full hash-chain authentication before every durable audit append;
- retained process-wide per-path serialization, OS file locking, bounded entry/file sizes, and atomic platform-authenticated checkpoints;
- added a negative regression proving equal-length middle-record tampering blocks append without changing journal bytes or checkpoint;
- aligned runtime, source evidence, product template, release gate, tests, and validator on `authenticated-checkpoint-v3`;
- retained exact synthetic-fixture history acknowledgements while leaving provider-side credential revocation as an external gate.

### BLE effect authority

- replaced shared mutable iOS peripheral delegate authority with immutable `PeripheralAttemptToken` ownership containing peripheral identity, side, generation, and nonce;
- added a retained delegate proxy for each current attempt and required every service, characteristic, notification, value, and write-readiness callback to pass current-token and selected-peripheral ownership before state mutation;
- placed cancelled CBPeripheral identifiers behind `RetiredConnectionBarrier`, preventing same-peripheral reassignment until the old terminal central-manager callback is consumed;
- changed iOS failure and disconnect callbacks to consume retired-attempt barriers before clearing readiness, pending writes, characteristics, or publishing Flutter state;
- removed the legacy “not left means right” callback classification; an unknown peripheral now has no authority and is ignored/cancelled;
- added pair identity to Android/iOS connection and response events, and required both native write paths to compare Flutter's expected pair identity and generation to current authority before accepting bytes;
- changed `EvenG1Transport` receipt, in-flight, and fingerprint authority from caller string alone to `(pair identity, generation, side, caller key, payload SHA-256)`;
- made authority storage bounded and fail closed at capacity rather than evicting a same-generation receipt that could suppress duplicate-effect protection;
- changed disconnect cleanup to select pending owners by generation and leg; one-leg disconnect never clears the opposite leg's existing uncertain-write quarantine;
- limited quarantine release to matching late response, explicit exact-leg reconciliation, retirement of the exact generation, or terminal disposal;
- rejected every command/ack response lacking a positive generation and exact non-placeholder pair identity before it can touch a pending slot or uncertain-write quarantine.

### Hostile regression evidence

- `test/runtime/even_g1_transport_authority_test.dart` proves cross-side, cross-generation, and cross-pair key separation, payload-drift rejection, captured native authority, and pre-write failure without authority;
- `test/runtime/ble_request_slot_test.dart` proves per-leg and per-generation quarantine isolation and selective disconnect cleanup;
- `test/runtime/ble_manager_authority_test.dart` drives a native-accepted right-leg write to ACK timeout, reports a left-leg disconnect, proves the right-leg replay remains quarantined, and rejects missing, zero, stale, wrong-pair, and cross-generation response authority;
- `test/runtime/even_g1_transport_authority_test.dart` proves an unscoped or mismatched native response is indeterminate rather than promoted to the captured connection authority;
- `ios/RunnerTests/RunnerTests.swift` proves a generation-N token cannot own generation N+1, an unknown peripheral cannot fall through to right-leg authority, the retired-peripheral barrier must be consumed, and retiring one leg does not retire the other.

### Privacy and documentation

- replaced stale Android/iOS G1 BLE documentation with current readiness, callback ownership, scoped idempotency, disconnect, request-correlation, and speech behavior;
- updated the machine-readable G1 BLE contract with callback, idempotency, native pre-write, reconnect-barrier, and quarantine rules;
- aligned the canonical plan, Project State, Current State, Evidence Index, release contract, product evidence template, and Gap Ledger on revision `2026-09-01-g8`;
- removed all connector authority/tool-output probe files and made their reintroduction a repository-contract failure;
- made assistant transcript/answer history explicit opt-in, disabled it by default on every application start, limited it to process memory, and made opt-out immediately destructive;
- retained controller and widget regressions plus a repository contract test for the history-consent boundary.

## Exact-head source exit

The code and deterministic tests above are E0–E3 claims until one unchanged PR head completes all seven required jobs:

1. `repository-contracts`
2. `flutter`
3. `android-native`
4. `ios-native`
5. `native-sanitizers`
6. `secret-and-boundary-scan`
7. `source-evidence`

The resulting `hepta-source-evidence-<exact-head-sha>` artifact must contain and bind the expected seven evidence files to the same commit and tree. A parent run, cancelled run, stale approval, locally generated bundle, or PR-body SHA is not E4.

## Evidence ceiling

Physical G1, production identity/attestation, provider revocation, complete repository administration, vendor firmware/OTA, production OAuth/realtime, independent assurance, signing, pilot, rollout, and store release remain E5–E7 gates. This remediation intentionally leaves them blocked rather than manufacturing evidence.
