# Realtime admission and expired-session cleanup runbook

Owner: cloud. Scope: local realtime activation admission, not production provider
acceptance. Design: `docs/development/REALTIME_ADMISSION.md`.
Contract: `contracts/realtime-admission-v1.json`. HG-0087/realtime remains OPEN.

## Upgrade preconditions

Authenticate the host caller and subject/session before invoking this library.
Supply a trusted current Unix-seconds clock to `DurableRealtimeStore(clock=...)`.
Remove the old per-call `now` argument; never replace it with a lambda capturing
client JSON or request arrival time. Validate clock operation before reopening
mutation ingress. An invalid or regressing operation clock cannot admit a new
session; fixing the clock does not un-revoke a denied session.

Stop/drain all old service processes for this code upgrade. Marked intact v2
storage stays v2 and is not rewritten; that SAME marker cannot keep an old binary
from reopening it. There is no mixed-version rollout or safe binary downgrade
claim. Do not automatically restart an old image after a failed deployment.
Keep mutation ingress disabled while diagnosing startup or compatibility errors.

Unknown versions, preexisting unmarked tables, or a missing component table fail
startup. Do not remove a marker, recreate an empty cleanup outbox or manufacture
missing ticket/attempt records to make startup pass. Preserve the original local
SQLite database and journals; privileged row changes and old snapshots are not
protected by an external anti-rollback service in this component.

## Normal operation and time semantics

A ticket's lifetime bounds initial activation completion, not the duration of an
already-active conversation. Enforce production conversation lifetime and identity
revocation in the separate authenticated session service. `require_generation`
only checks local active state/generation; it is not device or tool authority.

Provider activation is one-shot after durable reservation. The adapter must honor
its remaining timeout and must not transform a retry into another remote session.
Only return current-generation session state from this gateway to its intended
caller. Model/audio outputs cannot supply final mutation authority.

Alert on clock errors, activation expiry, unknown readback, pending cleanup,
worker exhaustion and storage exceptions. Log safe error codes and aggregate
counts, not ticket bytes, credentials, transcripts or private provider errors.
Provider/subject metadata in SQLite needs operational encryption and access
control even though plaintext tickets are hashed rather than stored.

## Expired activation and crash recovery

Read `pending_recovery()` through an authorized operator path. For an unresolved
attempt, `reconcile` queries the original remote session only. It never calls
activation a second time. If the original consumed ticket has expired, local
state becomes revoked and remote discovery is cleanup-only, not renewed consent.
Increasing constructor TTL or issuing a new request time cannot extend that
persisted deadline. A revoked session ID cannot be reissued.

Known remote sessions that lose admission are queued for idempotent revoke before
an error is raised. Drain those jobs with `drain_revocations`. A timeout, process
exit or failed remote revoke must leave pending custody. A lookup returning None
is unknown, not evidence of deletion. Keep remote cleanup and local denial as
separate facts; do not issue a fabricated provider receipt.

Each cleanup batch shares one caller timeout across jobs and lookup/revoke legs.
A consumed caller budget leaves remaining jobs for another authorized drain
operation. SQLite locks and noncooperative worker/transport calls can still exceed
caller waiting budgets; hard process isolation and supervisor controls remain
necessary. Do not spawn replacement stores or unlimited worker pools to escape
saturation. The component does not install a background drain scheduler.

If an answer arrives after the caller timeout but before ticket expiry, local
activation remains uncertain and may only be resolved by readback within that
same deadline. If the admission deadline has passed, never use cached provider
success to reopen it. Do not rewrite generation, consumed-ticket state or expiry.

## Validation and acceptance

```bash
python3 -m unittest services.control_plane.test_durable_realtime \
  services.control_plane.test_realtime_custody \
  services.control_plane.test_realtime_admission -v
python3 tools/validate_repository.py
python3 tools/validate_repository_metadata.py
python3 tools/validate_production_authority.py
python3 tools/validate_source_coverage.py
python3 tools/validate_module_handoff.py
python3 -m unittest discover -s services -p 'test_*.py'
python3 -m unittest discover -s adapters -p 'test_*.py'
python3 -m compileall -q services adapters tools
```

Then require seven nonempty successful canonical CI jobs on one final unchanged
head and inspect its downloaded artifact. Eligible independent review, complete
main-protection readback, actual provider/device/retention qualification and the
known separate identity freshness defect remain unresolved acceptance conditions.
Local SQLite/provider fixtures are not live provider or production evidence.
Keep PR #101 Draft; no self-approval, merge, deployment, release or bypass.
