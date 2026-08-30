# Hepta Glasses OS

Hepta Glasses OS is the deterministic mobile edge and control-plane reference architecture for Even Realities G1-class smart glasses. The glasses provide low-power sensing, input, audio, and display; the companion application owns bounded device transport; the edge runtime admits and journals effects; a control plane provides identity, short-lived model/realtime access, capability routing, revocation, and recovery; isolated Codex workers may propose patches but never own final device or account authority.

Model, realtime, Skill, MCP, notification, document, webpage, transcript, and Codex content are untrusted proposals. Real side effects are schema-validated, policy-admitted, exact-argument bound, journaled before effect, idempotency-keyed, and reconciled whenever completion is uncertain.

## Product boundary

This repository began as a sanitized import of Even Realities' `EvenDemoApp`. It contains a Flutter companion, Android/iOS BLE integration, LC3/RNNoise source, deterministic edge-runtime contracts, reference cloud services, evidence tooling, and operational runbooks. It does **not** contain vendor-authorized G1 firmware, bootloader, secure-boot keys, production provider credentials, production signing identities, or proof of physical-device qualification.

The word “OS” therefore describes the distributed product boundary—device plane, mobile edge, control plane, capability adapters, and isolated workers—not ownership of the G1 firmware.

## Canonical truth

The active plan revision is `2026-08-30-g5`:

- [`docs/HEPTA_GLASSES_CANONICAL_DEVELOPMENT_PLAN.md`](docs/HEPTA_GLASSES_CANONICAL_DEVELOPMENT_PLAN.md)
- [`docs/CURRENT_STATE.md`](docs/CURRENT_STATE.md)
- [`docs/PRODUCT_BOUNDARY.md`](docs/PRODUCT_BOUNDARY.md)
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- [`docs/GAP_LEDGER.yaml`](docs/GAP_LEDGER.yaml)
- [`docs/EVIDENCE_INDEX.yaml`](docs/EVIDENCE_INDEX.yaml)

`docs/GAP_LEDGER.yaml` is machine-readable JSON stored with a `.yaml` suffix for compatibility with the existing evidence tooling. Source-closed entries are distinct from physical, deployed, administrative, upstream, independent-review, and release evidence.

## Implemented source foundation

- versioned event, intent, task, tool, lease, display, realtime, memory, qualification, and release contracts;
- deterministic packet framing, independent left/right readiness, generation fencing, exact response correlation, replay-safe receipts, and a G1 digital twin;
- journal-before-effect execution, exact-key in-flight de-duplication, bounded physical-effect scheduling, timeout indeterminacy, recovery, and authoritative reconciliation;
- bounded hash-chained JSONL audit with cross-instance/process coordination, an OS file lock, torn-tail detection, and fail-closed durable-storage startup;
- provider-neutral model gateway boundary with no permanent provider credential in the mobile product bundle;
- reference identity, short-lived token, rate-limit, realtime, capability, Skill, Memory, governance, qualification, SBOM, provenance, and release-gate services;
- a multi-ecosystem source SBOM covering Dart, Gradle, CocoaPods, build tools, and declared vendored LC3/RNNoise source;
- full-history credential-fingerprint scanning that never writes secret values into reports;
- Android/iOS native tests plus a host LC3 sanitizer and bounded fuzz harness;
- exact-head GitHub Actions evidence bound to one commit, tree, plan revision, and dependency inventory.

## Local source checks

```bash
python3 tools/validate_repository.py
python3 -m unittest discover -s services -p 'test_*.py'
python3 -m unittest discover -s adapters -p 'test_*.py'
python3 -m compileall -q services adapters tools
python3 tools/scan_repository_history.py --fail-on-current
flutter pub get
dart format --output=none --set-exit-if-changed lib test
flutter analyze --fatal-warnings
flutter test
bash tools/run_native_sanitizer_tests.sh
```

The history scanner requires a complete Git checkout. CI uses `fetch-depth: 0`. The native sanitizer harness requires Clang with AddressSanitizer, UndefinedBehaviorSanitizer, and libFuzzer support.

## Release truth

A passing source gate proves only the checked source head. It does not prove physical G1 performance, production KMS/HSM or attestation, vendor firmware authority, production OAuth/provider reconciliation, independent security/privacy/legal review, signed binaries, pilot outcomes, kill-switch operation, rollback, or store approval.

Those product claims remain blocked until their E5–E7 evidence is supplied and the non-overridable product release gate passes. See the [Gap Ledger](docs/GAP_LEDGER.yaml) and [release runbook](docs/operations/RELEASE_AND_ROLLBACK_RUNBOOK.md).

## Upstream and licenses

The import provenance is retained in [`UPSTREAM.md`](UPSTREAM.md). Repository licensing remains in [`LICENSE`](LICENSE). Vendored component scope and declared upstream licenses are recorded in [`third_party/components.json`](third_party/components.json); that manifest is part of the source SBOM and must be updated whenever vendored code changes.
