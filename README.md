# Hepta Glasses OS — active source candidate

This branch is the active candidate for the Hepta Glasses distributed edge runtime. The live pull-request head and tree, not prose, identify the candidate. Source, CI, simulator, and repository-authored evidence do not create physical-device, provider, vendor, signing, independent-assurance, pilot, store, or other E5–E7 authority.

Start with `docs/development/2026-09-03_BLOCKER_EXECUTION_PLAN.md`, `docs/REMEDIATION_GAP_LEDGER.json`, `docs/MODULE_COVERAGE.json`, `docs/MODULE_HANDOFF.json`, `docs/development/HG0087_PRODUCTION_IMPLEMENTATION.md`, and `docs/operations/HG0087_PRODUCTION_RUNTIME_RUNBOOK.md`.

## Current development and validation entry points

- `docs/development/MODULE_HANDOFF.md` and `docs/MODULE_HANDOFF.json` map the registered modules.
- `contracts/conformance/canonical-json-v1.json` is the shared Dart/Python vector set.
- `docs/HG0087_IMPLEMENTATION_STATUS.json` separates the seven still-open production slices.
- `contracts/realtime-speech-custody-v2.json` defines the realtime custody patch and explicitly pending speech requirements.

HG-0087 remains OPEN. Source increments now include realtime correctness,
committed-evidence custody and durable identity/broker verification. Identity design
and operations are in `docs/development/DURABLE_IDENTITY.md` and
`docs/operations/IDENTITY_AUTHORITY_RUNBOOK.md`. Production integration remains
explicitly open. Speech source is unchanged by these increments. Local tests are not exact-head CI, production tenancy, physical-device
qualification, independent review or release evidence. Continue in PR #101
without force-push, self-approval, self-merge or bypass.
