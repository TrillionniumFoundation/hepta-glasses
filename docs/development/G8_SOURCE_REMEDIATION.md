# G8 source-integrity and documentation remediation

Status: repository-side implementation record. It is not independent approval or product-release evidence.

## Closed source defects

- restored full hash-chain authentication before every durable audit append;
- retained process-wide per-path serialization, OS file locking, bounded entry/file sizes, and atomic v2 checkpoints;
- added a negative regression test proving equal-length middle-record tampering blocks append without changing journal bytes or checkpoint;
- aligned runtime, source evidence, product template, release gate, tests, and validator on `file-lock-checkpoint-v2`;
- retained exact synthetic-fixture history acknowledgements while leaving provider-side credential revocation as an external gate;
- replaced stale Android/iOS G1 BLE documentation with current readiness, disconnect, request-correlation, and speech behavior;
- added machine-readable Project State, platform capability matrix, and G1 BLE protocol contract;
- expanded the release runbook to the actual seven-job and seven-artifact contract.

## Evidence ceiling

These changes are E0–E3 until the exact PR head completes all required jobs and produces a content-verified artifact. Physical G1, production identity/attestation, provider revocation, repository administration, vendor firmware/OTA, production OAuth/realtime, independent assurance, signing, pilot, rollout, and store release remain E5–E7 gates.
