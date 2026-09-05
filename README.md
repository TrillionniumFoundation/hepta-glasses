# Hepta Glasses OS — active source candidate

This branch is the active candidate for the Hepta Glasses distributed edge runtime. The live pull-request head and tree, not prose, identify the candidate. Source, CI, simulator, and repository-authored evidence do not create physical-device, provider, vendor, signing, independent-assurance, pilot, store, or other E5–E7 authority.

Start with `docs/development/2026-09-03_BLOCKER_EXECUTION_PLAN.md`, `docs/REMEDIATION_GAP_LEDGER.json`, `docs/MODULE_COVERAGE.json`, `docs/MODULE_HANDOFF.json`, `docs/development/HG0087_PRODUCTION_IMPLEMENTATION.md`, and `docs/operations/HG0087_PRODUCTION_RUNTIME_RUNBOOK.md`.

## Current development and validation entry points

- `docs/development/MODULE_HANDOFF.md` and `docs/MODULE_HANDOFF.json` map the registered modules.
- `contracts/conformance/canonical-json-v1.json` is the shared Dart/Python vector set.
- `docs/HG0087_IMPLEMENTATION_STATUS.json` separates the seven still-open production slices.
- `contracts/realtime-speech-custody-v2.json` defines the realtime custody patch and explicitly pending speech requirements.

HG-0087 remains OPEN. Source increments now include realtime correctness,
committed-evidence custody, durable identity/broker verification and durable
capability intent/readback recovery. Identity design
and operations are in `docs/development/DURABLE_IDENTITY.md` and
`docs/operations/IDENTITY_AUTHORITY_RUNBOOK.md`. Production integration remains
explicitly open. Speech source is unchanged by these increments. Local tests are not exact-head CI, production tenancy, physical-device
qualification, independent review or release evidence. Continue in PR #101
without force-push, self-approval, self-merge or bypass.

## Durable capability development

`docs/development/DURABLE_CAPABILITIES.md`,
`docs/operations/DURABLE_CAPABILITY_RUNBOOK.md` and
`contracts/durable-capability-v1.json` describe the SQLite intent ledger,
single-use leases, conservative restart semantics and bounded provider readback.
It is a source component, not a deployed OAuth service or an encrypted payload
vault. Mutations remain disabled at the consumer entry point until authenticated
production composition and the applicable gates are satisfied.

The handoff index selects the current identity, realtime and capability designs;
these supersede the old in-memory-only descriptions for those durable components.
The legacy reference APIs remain documented separately. Structural validation of
26 module entries is not proof of semantic completeness or production readiness.

## Signed Skill package development

`docs/development/SIGNED_SKILLS.md`, `docs/operations/SIGNED_SKILLS_RUNBOOK.md`
and `contracts/signed-skill-package-v1.json` describe the publisher-bound Ed25519
package format and durable consent/version/revocation registry. This validates
immutable package bytes without extraction or execution. HG-0087/skills remains
OPEN for sandbox, egress, externally governed publisher trust/transparency,
authenticated consent and independent package qualification. The separate known
identity freshness defect and previously blocked identity/speech/Memory writes
are not repaired or published by this Skills increment.
