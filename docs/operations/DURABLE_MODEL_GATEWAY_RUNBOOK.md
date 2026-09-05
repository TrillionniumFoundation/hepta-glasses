# Durable model gateway operations

Owner: ai-platform. Scope: local request custody and the text-only foreground
Responses adapter. HG-0087/model remains OPEN. Design:
`docs/development/DURABLE_MODEL_GATEWAY.md`. Contract:
`contracts/durable-model-gateway-v2.json`.

## Before connecting a service

Use a trusted local operator-owned directory and restrictive permissions. SQLite
metadata is not encrypted by this module. Supply operational encryption, access
control, backups and anti-rollback procedures before retaining personal metadata.
Do not use network filesystems, public temporary directories or restored old
snapshots. Persistent idempotency/revocations cannot survive intentional deletion
of their database; deleting it is not a supported recovery procedure.

Authenticate every caller and session out of band. Obtain actual approval to send
the exact question/context to the selected provider/deployment. Bound `expires_at`
to that authority and give the gateway a trusted host `clock`. Do not accept
subject/session/expiry directly from unauthenticated JSON. The deterministic
`app.py` endpoint is not connected to this adapter, and this increment does not
repair the separately blocked identity enrollment-freshness finding.

Select and qualify an exact provider model ID. `ResponsesProvider.binding_id`
binds the model, a non-secret deployment label, fixed endpoint/profile and output
budget; use it as `provider_binding`. The deployment label must remain tied to
the same externally governed project when vault credentials rotate. Credentials
come only from a trusted bounded vault callback. No real credential or question
belongs in source, fixtures, reports or logs.

The API profile disables response storage, streaming, background tasks and tools.
Verify actual tenant retention, billing, regional requirements, rate limits and
abuse monitoring separately. `store=false` is not proof of Zero Data Retention.
Keep production routing disabled until those requirements and authenticated
service composition are qualified. No fixture proves provider acceptance.

## Execute, monitor and cancel

Use a subject-scoped stable idempotency key for one exact request and absolute
expiry. Never change its prompt, provider binding or expiry to make a retry pass.
Each initial reservation permanently consumes its daily attempt budget. Daily
quota is not a price ceiling, and cancellations do not promise refunded usage.
Add independent provider-side spend controls and operational monitoring.

On success, deliver only the checked answer returned by `execute`; metadata
receipts contain hashes, not a cached answer or execution permit. Keep model text
outside policy/device/tool authority. A later cancellation cannot retract an
already delivered response; downstream effects need their own final authorization.

On cancellation, call `cancel` or subject-scoped `revoke_session` and retain the
database. The response explicitly confirms local delivery denial only. A running
foreground provider request may finish and incur charges. Do not report remote
cancellation, deletion, refund or a stopped job without actual provider evidence.
Revocation remains available when the normal trusted clock is unhealthy.

Use only fixed error codes and restricted counters for diagnostics. Never log
HTTP headers/bodies, credential exceptions, prompt/context, answers or unfiltered
provider IDs. Metadata and digests still require privacy controls. Audit events
are local records, not independent receipt or external transparency evidence.

## Timeout, process failure and recovery

After reservation, any ambiguous outcome stays prepared/indeterminate. A live
claim blocks duplicate work across processes; after its lease, only bounded
readback can be reserved. Never replay generation to turn an unknown result into
a success. Exhausting readback budget does not mean remote work did not happen.

The foreground nonstored Responses adapter intentionally cannot retrieve an
answer from `X-Client-Request-Id`. Its readback returns unknown without a network
call. Preserve that state and investigate real provider records through approved
operator processes. Any deliberately new request after investigation requires
fresh authority and a new key, and is not deduplication of the ambiguous request.

A crash before reservation commit leaves neither reservation nor its event. A
crash after reservation retains the uncertain request; a completed denial remains
terminal across restart. `recoverable` is a bounded metadata inventory, not an
automatic replay queue. It can list expired rows but does not extend authority.

Database or policy/schema errors stop admission. Do not rewrite version markers,
remove old `requests`/`revoked_sessions`, drop tombstones, patch expiry or restore
a stale checkpoint. The unversioned predecessor and incomplete v2 schemas need a
separately reviewed migration. There is no automated import/reset/unsuspend API.
At lifetime row capacity stop new work and perform a reviewed archival/migration
that retains global idempotency and denials; do not empty the ledger.

## Resource boundary and acceptance

Bound replica count as well as per-instance worker pools. A hung worker keeps its
permit; the caller times out, but Python threads do not supply hard process
termination. DNS, a hostile slow peer or a noncooperative vault/provider can need
process/service isolation and egress controls. Do not grow pools or automatically
create replacement gateway objects to escape saturation.

Run:

```bash
python3 -m unittest services.model_gateway.test_production \
  services.model_gateway.test_model_boundaries \
  services.model_gateway.test_responses_provider -v
python3 tools/validate_repository.py
python3 tools/validate_repository_metadata.py
python3 tools/validate_production_authority.py
python3 tools/validate_source_coverage.py
python3 tools/validate_module_handoff.py
python3 -m unittest discover -s services -p 'test_*.py'
python3 -m unittest discover -s adapters -p 'test_*.py'
python3 -m compileall -q services adapters tools
```

Then require all seven canonical CI jobs nonempty/success on one final head,
download and verify its exact artifact, obtain eligible independent review and
resolve objections. Do not transfer predecessor CI credit or dismiss the known
identity and product blockers. A local provider fixture or wire mock is not a
live TLS/provider, authenticated ingress, remote cancellation or production test.
Keep Draft; no merge, automatic rollout, deployment or release.
