# Hepta Glasses OS — active source candidate

A distributed AI-native companion runtime for Even G1-class glasses: phone-side
deterministic BLE/policy/audit execution, reference cloud control-plane services,
and isolated development tools. This repository is not vendor firmware and the
candidate is not a production release. Models, Skills, MCP, and Codex propose
work; deterministic authority admits, journals, executes, and reconciles side
effects.

## Active development authority

The active remediation package is PR #101 on
`work/hepta-g10-trusted-openssl-custody-20260902`; it is not merged into `main`.
The live pull-request head and tree are authoritative. Do not copy a SHA, workflow
run, artifact, or review from this prose: every push or base movement requires a
new exact-head qualification and independently bound review.

Start with:

- `docs/development/2026-09-03_BLOCKER_EXECUTION_PLAN.md` — active all-gap work,
  execution order, source/external boundaries, and acceptance;
- `docs/REMEDIATION_GAP_LEDGER.json` — current repository backlog and exact
  evidence state, including HG-0090/HG-0091 source closure;
- `docs/MODULE_COVERAGE.json` — flattened G8/G9/G10 ownership plus the plugin;
- `docs/MODULE_HANDOFF.json` — machine-readable engineering handoff dimensions
  for all 26 modules;
- `docs/development/MODULE_HANDOFF.md` — human-readable handoff index;
- `contracts/conformance/canonical-json-v1.json` — shared Dart/Python vectors;
- `docs/development/SOURCE_COVERAGE_AND_STATE.md` — reverse source coverage and
  truthful current-state projection;
- `docs/development/REFERENCE_RUNTIME_HARDENING.md` — bounded capability calls
  and current-consent Memory;
- `plugins/hepta-glasses-agent-os/DEVELOPMENT.md` — read-only plugin launch and
  tool contract; and
- `docs/operations/RELEASE_AND_ROLLBACK_RUNBOOK.md` — authenticated product gate,
  kill-switch, rollback, and release custody.

`docs/CURRENT_STATE.md` and `docs/PROJECT_STATE.json` describe the inherited G8
baseline, including its 22-module registry; do not confuse those historical
counts with the current flattened registry. The canonical invariants in
`docs/HEPTA_GLASSES_CANONICAL_DEVELOPMENT_PLAN.md`, `docs/PRODUCT_BOUNDARY.md`,
`docs/ARCHITECTURE.md`, `docs/THREAT_MODEL.md`, `docs/PRIVACY_MODEL.md`, and
`docs/CAPABILITY_MODEL.md` remain applicable. `docs/README.md` indexes the retained
G8/G9/G10 guides and ADRs.

## Supported source and explicit limits

The mobile source contains dual-leg G1 BLE, bounded text/bitmap/notification
protocols, LC3 processing, deterministic policy, leases, audit, cancellation,
and conservative indeterminate-effect semantics. Android PCM-to-ASR remains
unavailable fail-closed; iOS speech is conditional on permission, locale, and
device support. Production mutation authority, deployed model/realtime/OAuth
integrations, persistent encrypted Memory, asymmetric Skill execution, and live
provider receipts are not supplied by the current reference implementations.

Capability timeouts and post-dispatch errors retain indeterminate receipts;
timed-out workers retain bounded capacity rather than authorizing replay. Memory
applies current consent atomically and remains process-memory only. The plugin
exposes development snapshots/previews and never device mutations. Canonical
fingerprints accept string-keyed finite JSON only.

Physical qualification preserves raw trace acquisition order. Timestamp
regression or incomplete/non-contiguous capture sequence now fails; production
scenarios require minimum latency/telemetry/packet samples and injected,
observed, and recovered fault evidence. These controls do not create physical
E5 evidence.

## Product release authority

`tools/evaluate_release_gate.py --mode product` does not trust status strings or
booleans written in a release JSON file. It invokes the G10 external-evidence
validator under trusted current time, exact source commit/tree, the verified
OpenSSL boundary, and the out-of-band
`HEPTA_EXTERNAL_TRUST_REGISTRY_SHA256` pin. All twelve authority-owned gaps,
issuer classes, accepted review-set integrity, and final closure are required.
There is no override.

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
lanes, and content-verified source SBOM/provenance generation. Only a successful
unchanged-head seven-context run with its independently verified artifact is E4.
Local tests, queued/skipped jobs, metadata summaries, and prior-head artifacts do
not substitute for that result.

## Release boundary

Keep exact-head review, full protection readback, physical G1 traces, provider
credential revocation, KMS/HSM/attestation, production adapters, vendor firmware
authority, independent assurance, signed binaries, pilot/rollback, and store
evidence separate. E0–E4 do not close E5–E7. The implementing identity does not
self-approve, self-merge, weaken protection, or fabricate authority evidence.

The upstream import history is preserved in `UPSTREAM.md`; the BSD-2-Clause
notice remains in `LICENSE`. Historical import instructions are not current
production credential-handling instructions.
