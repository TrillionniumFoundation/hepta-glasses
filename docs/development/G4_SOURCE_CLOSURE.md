# G4 source closure package

Revision: `2026-08-30-g4`

## Scope

This package closes the source-actionable gaps found after the G3 mobile/runtime hardening review. It is stacked on PR #9 and reviewed in PR #10.

## Implemented closure

| Area | Closure |
|---|---|
| Exact-head CI | Reproducible Flutter/Gradle/CocoaPods inputs, semantic source-evidence binding, read-only checks, Android native unit tests, and iOS XCTest. |
| Identity | Stable audience-mismatch failure and regression coverage instead of an accidental runtime `NameError`. |
| Audit and effects | Serialized and file-locked JSONL append, concurrent request coalescing, bounded physical-effect scheduling, terminal-journal failure protection, and recovery-safe indeterminate receipts. |
| BLE | Independent left/right readiness, connection-generation fencing, exact next-response matching, late-response quarantine, no blind replay after a possibly applied write, and persisted uncertain receipt semantics. |
| Native audio | Strict LC3 frame size/bounds checks, allocation and decoder-result checks, persistent iOS decoder state reset only at explicit assistant-session start, and malformed-frame native tests. |
| Assistant | Native and Dart generation binding, final-ASR waiting, stale-result rejection, truthful Android ASR unavailability, and completion only after final display acknowledgement. |
| Release configuration | Non-template application identifiers, no Android debug-signing fallback for release, unified iOS deployment target, and locked CocoaPods state. |

## Required checks

```bash
python3 tools/validate_repository.py
python3 -m unittest discover -s services -p 'test_*.py'
python3 -m unittest discover -s adapters -p 'test_*.py'
python3 -m compileall -q services adapters tools
flutter pub get
dart format --output=none --set-exit-if-changed lib test
flutter analyze --no-fatal-infos --no-fatal-warnings
flutter test
flutter build apk --debug
(cd android && ./gradlew testDebugUnitTest)
flutter build ios --simulator --debug
xcodebuild test -workspace ios/Runner.xcworkspace -scheme Runner -destination '<available iPhone simulator>' CODE_SIGNING_ALLOWED=NO
```

The successful CI artifact must be bound to the exact PR-head commit and tree.

## Explicit non-closure

This package does not claim physical G1 qualification, production KMS/HSM or attestation, active `main` protection, vendor firmware authority, production provider/OAuth infrastructure, independent assurance, signing, pilot, staged rollout, kill-switch, rollback, or store approval. Those gates remain open until E5–E7 evidence exists.
