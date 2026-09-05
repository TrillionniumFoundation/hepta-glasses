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

## Durable model request development

`docs/development/DURABLE_MODEL_GATEWAY.md`,
`docs/operations/DURABLE_MODEL_GATEWAY_RUNBOOK.md` and
`contracts/durable-model-gateway-v2.json` describe atomic subject-scoped quota and
idempotency, readback-only crash recovery, cancellation/revocation fencing and a
text-only foreground Responses HTTPS adapter. The v2 API requires explicit host
clock, provider binding and absolute consent expiry; unversioned databases are
rejected rather than reset. No credentials or live provider tests are included.
`app.py` remains a separate development endpoint. Local cancellation is not remote
termination; an uncertain nonstored foreground response cannot be reconstructed
by retrying its POST. HG-0087/model remains OPEN for authenticated composition,
real provider/retention/billing qualification, remote cancellation/recovery,
service isolation, encrypted metadata and independent acceptance.

## Calendar capability implementation

`docs/development/GOOGLE_CALENDAR_CAPABILITY.md`,
`docs/operations/GOOGLE_CALENDAR_CAPABILITY_RUNBOOK.md` and
`contracts/google-calendar-capability-v1.json` describe the single owned-calendar
create/get adapter. It uses the durable capability gateway and a final pre-POST
lease/revocation check after OAuth/TLS. Missing/conflicting events stay unknown;
recovery never replays POST. OAuth consent/refresh custody, real account ownership,
authenticated ingress, encrypted payload recovery and provider qualification remain
open. No consumer route or real credentials are enabled by this source increment.

## Source boundary policy for cloud providers

`docs/development/SERVER_PROVIDER_BOUNDARY.md` explains the exact-file, exact-
SHA-256 declarations in `contracts/server-provider-boundary-v1.json`. They permit
only the named cloud transport's endpoint markers and its existing wire-test
markers, not credentials or consumer-side provider access. Repository and CI
boundary jobs share the same validator; secret/bypass and history checks remain.
This source-policy correction is not production qualification, independent
approval or closure of HG-0087.
