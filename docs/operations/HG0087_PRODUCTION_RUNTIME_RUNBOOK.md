# HG-0087 realtime runtime runbook

Status: source-candidate operational contract, not a deployment claim. HG-0087
remains OPEN. This patch changes realtime custody only. Speech production repair,
provider adapters and the authenticated HTTP service are not deployed by this
runbook. Do not expose these Python methods directly to unauthenticated callers.

## 1. Operator prerequisites

Select an operator-owned, persistent local SQLite path with restrictive directory
and file permissions. Deploy one supported schema version. Supply a concrete
RealtimeProvider that has bounded network timeouts, stable session/receipt IDs,
authoritative activation lookup, and idempotent revocation. Its credentials must
come from deployment identity or a secret manager, not source, logs or tickets.

The authenticated service must derive subject/session ownership and UTC time
before calling the store. Reject client-supplied authority or clock overrides.
If this integration does not exist, keep the service unavailable. There is no
production start command in this patch because its service layer remains OPEN.

## 2. Pre-deployment validation

Run the targeted realtime tests, all repository/metadata/production-authority and
coverage/handoff validators, service/adapter tests, compile checks, Flutter,
Android, iOS, sanitizers and history scan on one unchanged source candidate.
Read the content-addressed evidence artifact and obtain independent review.
Local tests alone do not qualify the current head or a deployment.

Read the database component schema before rollout. Unknown versions require an
explicit migration review; never edit a marker to suppress the rejection.
Quiesce writers, create a SQLite-consistent backup, perform migration and test
recovery against a non-production copy. Database rollback is not allowed to
restore previously revoked authority.

## 3. Startup and interrupted-work recovery

Instantiate DurableRealtimeStore through the authenticated service composition.
Call `pending_recovery(limit=100)` and resolve returned identifiers in bounded
batches. For activating/indeterminate state, call `reconcile(session_id)`; this
is readback, never a second activation. A None result or transient provider error
keeps the session uncertain and requires further provider investigation.

Call `drain_revocations(limit=20, timeout_seconds=5)` for pending cleanup. Its
return value is the remaining count, not a release approval. Unknown provider
identity or a failed revoke remains pending across process restarts. Late results
cannot re-enable a locally revoked session.

Read-only storage diagnostics can use these queries under the operator's normal
access controls; do not dump ticket digests or full databases into logs:

```sql
SELECT state, COUNT(*) FROM sessions GROUP BY state;
SELECT state, COUNT(*) FROM realtime_revoke_outbox GROUP BY state;
SELECT component, version FROM hepta_component_schema;
```

## 4. Revoke and lost-device response

Revoke every known affected realtime session through the authenticated authority.
Local state and generation must deny further use before external revoke is
attempted. A provider_revoke_pending error must be treated as an alert, not as
permission to restore the session. Repair provider connectivity and drain only
cleanup jobs. The wider subject/device/token lost-device integration remains
OPEN and cannot be replaced by this session-level procedure.

Do not clear a pending job based on timeout, a screenshot or an edited JSON row.
Require authoritative provider evidence for external completion. Create a new
subject-authorized session rather than reusing a revoked session ID.

## 5. Monitoring, capacity and failure handling

Monitor pending activating/indeterminate sessions, pending cleanup count, database
size, capacity rejections, lock contention and bounded-worker saturation. Alert
on any unresolved cleanup and establish deployment-specific response objectives
before production. This implementation has no background scheduler or automatic
record purge; the service operator must supply scheduling and retention policy.

At capacity, stop new admission and investigate. Do not evict consumed tickets,
attempts or revocation tombstones merely to obtain a green metric: eviction can
reintroduce replay. Plan reviewed archive/retention migration. If a provider
worker never returns, its bounded permit remains occupied; repair or replace the
isolated provider worker, without assuming its remote operation failed.

No raw audio, transcript, bearer token, provider credential or ticket body belongs
in ordinary logs or evidence. Retain only authorized identifiers, state and
redacted error codes. Export and backups require separate access controls.

## 6. Rollback, acceptance and unresolved boundaries

Rollback application binaries only with a schema-compatible version. After a
rollback, re-run unresolved-work and revoke-outbox recovery before accepting new
traffic. Never restore stale revocation state, replay activate, or change a
terminal revoked record to active. If compatibility cannot be proved, stop
admission and perform a forward repair.

Acceptance requires real provider readback/revoke drills, restart and dependency
outage exercises, identity integration, an independently reviewed source artifact
and separate production evidence. No real tenant, physical G1, KMS/HSM, platform
attestation, signing, store or release result is asserted here. The implementation
index and active blocker plan remain authoritative for the remaining work.
