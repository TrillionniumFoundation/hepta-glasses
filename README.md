# Hepta Glasses OS — source candidate

A distributed AI-native companion runtime for Even G1-class glasses: phone-side
deterministic BLE/policy/audit execution, reference cloud control-plane services,
and isolated development tools. This repository is not vendor firmware and the
candidate is not a production release. Models, Skills, MCP and Codex propose work;
deterministic authority admits, journals, executes and reconciles side effects.

## Active development authority

The active remediation package continues on PR #101 and
`work/hepta-g10-trusted-openssl-custody-20260902`; it is not merged into main.
Read the live PR head rather than copying an old SHA or successful artifact.
No old G8/G9/G10 receipt automatically qualifies a later repair commit.

Start with:

- `docs/development/2026-09-03_BLOCKER_EXECUTION_PLAN.md` — execution order and acceptance;
- `docs/REMEDIATION_GAP_LEDGER.json` — active findings and their exact evidence state;
- `docs/MODULE_COVERAGE.json` — flattened G8/G9/G10 ownership plus the plugin supplement;
- `docs/MODULE_HANDOFF.json` — machine-readable API/state/failure/configuration/migration/operations/test/evidence dimensions for all 26 modules;
- `docs/development/MODULE_HANDOFF.md` — human-readable engineering handoff for every flattened module;
- `contracts/conformance/canonical-json-v1.json` — vectors consumed by Dart and Python fingerprint tests;
- `docs/development/SOURCE_COVERAGE_AND_STATE.md` — reverse coverage and truthful current-state projection;
- `docs/development/REFERENCE_RUNTIME_HARDENING.md` — bounded capability calls and current-consent Memory;
- `plugins/hepta-glasses-agent-os/DEVELOPMENT.md` — actual read-only plugin launch and tool contract.

`docs/CURRENT_STATE.md` and `docs/PROJECT_STATE.json` describe the inherited G8
baseline, including its 22-module registry; do not confuse those historical
counts with the current flattened registry. The canonical product invariants in
`docs/HEPTA_GLASSES_CANONICAL_DEVELOPMENT_PLAN.md`, `docs/PRODUCT_BOUNDARY.md`,
`docs/ARCHITECTURE.md`, `docs/THREAT_MODEL.md`, `docs/PRIVACY_MODEL.md` and
`docs/CAPABILITY_MODEL.md` remain applicable. `docs/README.md` indexes the retained
G8/G9/G10 guides and ADRs. Reverse source ownership and handoff validators check
coverage and structured dimensions; neither turns reference code into production.

## Supported source and explicit limits

The mobile source contains dual-leg G1 BLE, bounded text/bitmap/notification
protocols, LC3 processing, deterministic policy, leases, audit and cancellation.
Android PCM-to-ASR remains unavailable fail-closed; iOS speech is conditional on
permission, locale and device support. Production mutation authority, deployed
model/realtime/OAuth integrations, persistent encrypted Memory and live provider
receipts are not supplied by the Python reference implementations.

Capability timeouts and post-dispatch errors preserve indeterminate receipts;
timed-out workers retain a bounded capacity permit, not a right to retry. The
Memory reference applies current consent atomically and remains process-memory
only. The plugin exposes development snapshots/previews, never device mutations.
Canonical fingerprints accept string-keyed finite JSON only; Dart and Python
consume the same committed vectors and reject non-finite values before hashing.

## Validation

```bash
python3 tools/validate_repository.py
python3 tools/validate_repository_metadata.py
python3 tools/validate_production_authority.py
python3 tools/validate_source_coverage.py
python3 tools/validate_module_handoff.py
python3 -m unittest discover -s services -p 'test_*.py'
python3 -m unittest discover -s adapters -p 'test_*.py'
python3 -m compileall -q services adapters tools
python3 tools/repository_snapshot.py
flutter pub get
dart format --output=none --set-exit-if-changed lib test
flutter analyze --no-fatal-infos
flutter test
bash tools/run_native_sanitizers.sh build/evidence/source-native-sanitizer.json
```

CI additionally performs full fetched-history scanning, both native platform
lanes and content-verified source SBOM/provenance generation. Only a successful
unchanged-head seven-context run with its verified artifact is E4. Local tests,
queued/skipped jobs and metadata summaries cannot substitute for that result.

## Release boundary

Keep independent exact-head review, full protection readback, physical G1 traces,
provider credential revocation, KMS/HSM/attestation, production adapters, vendor
firmware authority, independent assurance, signed binaries, pilot/rollback and
store evidence separate. E0–E4 do not close E5–E7. The implementing agent does not
self-approve, self-merge, weaken protection or fabricate authority evidence.

The upstream import history is preserved in `UPSTREAM.md` and the BSD-2-Clause
notice remains in `LICENSE`. Historical import instructions are not current
production credential-handling instructions.
