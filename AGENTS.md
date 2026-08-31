# Codex operating contract for Hepta Glasses OS

## Scope

Work only inside this repository and preserve `UPSTREAM.md` and `LICENSE`. Treat the canonical plan, Current State, Gap Ledger, Evidence Index, schemas, contracts, third-party inventory, and exact-head CI artifact as current truth.

## Required behavior

- Revalidate exact base, head commit, and tree before every package.
- Continue in one isolated package branch/PR; never merge your own PR.
- Do not claim physical device, production credentials, vendor firmware, independent review, pilot, signing, or release closure from source tests, simulators, synthetic data, or the digital twin.
- Keep model, realtime, Skill, MCP, notification, document, webpage, transcript, and Codex output outside final execution authority.
- Journal mutations before effect and preserve exact idempotency across retry, restart, timeout, crash windows, and reconciliation.
- Never add provider keys, OAuth refresh tokens, signing keys, KMS material, account credentials, raw audio, or sensitive transcripts to source, fixtures, logs, prompts, or artifacts.
- History/security reports may contain only metadata and one-way fingerprints, never recovered secret values.
- Never introduce sandbox bypass, unrestricted full access, hidden mutation MCP tools, or self-merge.
- Preserve bounded payloads, storage, queues, scopes, domains, deadlines, cancellation, generation fencing, and fail-closed recovery.
- A source gate may close only with exact-head evidence. A blocked external/admin/upstream gate moves only with its required E5–E7 evidence.
- A source SBOM cannot substitute for a signed binary SBOM or artifact attestation.

## Required checks

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

For source-evidence generation:

```bash
CI_REPOSITORY_CONTRACTS=success \
CI_FLUTTER=success \
CI_ANDROID_NATIVE=success \
CI_IOS_NATIVE=success \
CI_NATIVE_SANITIZERS=success \
CI_SECRET_SCAN=success \
python3 tools/build_source_evidence.py --output-dir build/evidence
python3 tools/evaluate_release_gate.py \
  --bundle build/evidence/source-release-bundle.json --mode source
```
