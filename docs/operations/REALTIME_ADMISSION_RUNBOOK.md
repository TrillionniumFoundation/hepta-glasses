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

Stop/drain all old service processes and disable new mutation ingress before
upgrading. Storage is now realtime v3. Ordinary startup refuses v2; perform the
explicit offline `migrate_realtime_v2` only on the existing intact WAL database.
Both lookup and revoke attempt limits are required, from 1..32 (new-store defaults
are 8). The migration allocates a NEW post-upgrade allowance for legacy work:
prior v2 attempts were uncounted and must not be represented as zero.

The migration preserves all four legacy tables' rows and ticket deadlines,
adds the three budget/policy tables and updates the marker in one transaction.
Failure rolls back. Re-running migration on v3, changing limits on reopen,
missing files/markers/tables, or inconsistent counters fails closed. There is no
counter-reset or implicit migration API. An old binary rejects v3 on reopen but
an already-running old process is not stopped by a marker. This is not a rolling
upgrade; verify old workers have actually exited before enabling the new service.

Keep SQLite and journals intact. Do not delete exhausted counter rows, recreate
an empty cleanup table, lower a marker, restore stale snapshots or construct a
new database to recover. The component has no externally anchored anti-rollback
or safe destructive compaction protocol. Clock/identity problems remain separate
operational incidents; the migration does not create consent or provider proof.

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
Lookup and known-revoke attempts also consume persistent, nonrefundable budgets
before I/O. Exhausted jobs stay pending, but the drain selects non-exhausted jobs
with the least prior attempts so one failure cannot starve every later job.
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
  services.control_plane.test_realtime_admission \
  services.control_plane.test_realtime_recovery_budget \
  services.control_plane.test_realtime_result_custody -v
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


## Budget-exhaustion response

Read `recovery_status(session_id)` through the authenticated operator path. A
`realtime_readback_budget_exhausted` error or `exhausted_pending>0` is an unresolved
remote-state incident, not successful cleanup. Preserve both the original
admission and attempt inventories. Unknown lookup jobs remain in
`pending_recovery` even when no further automated calls can be reserved.

Escalate using the actual provider's lookup/revocation process and retain genuine
provider facts. Do not resubmit activation, increase the stored budget, patch
counter values or represent a local summary as independent acceptance. This
source has no administrator reset endpoint. Operational repair outside its
bounded automated path requires a separately reviewed procedure. A crashed
attempt may have reached the provider; its budget remains spent. A transaction
failure before reservation cannot be reported as a completed remote action.

The tests use fixture providers only. No real provider is contacted by the test
suite, and no automated job created here performs background work after it exits.


## Conflicting results and cleanup acknowledgement

Treat realtime_provider_identity_conflict as a terminal local session denial,
not merely a failed caller retry. Inspect recovery_status and pending_recovery:
the original and alternate owned remote IDs can each require cleanup. The
operator must preserve all jobs and their spent budgets across restart. A
successful primary cleanup is insufficient while an alternate known job remains
pending; explicit revoke and the drain now process those additional jobs.
Do not overwrite the stored provider identity or restore an active generation.

realtime_provider_owner_conflict means an observation named an ID belonging to
another retained local session or its cleanup. The contender stays revoked with
lookup-only responsibility. Do not revoke the other session to clear that error;
resolve attribution using authentic provider records through the approved
operator process. These checks assume one correctly governed provider namespace
per database. They do not establish real account/tenant binding or response trust.

The adapter's revoke method must return None only on its verified success and
raise on uncertainty. Boolean/error-object returns cannot complete an outbox job.
No return value from this trusted callback is independent evidence. If the
provider operation happened but the local completion transaction failed, retain
pending custody and its spent attempt; retry only idempotent cleanup within the
existing allowance. Missing or rebound jobs are storage incidents, not success.

In recovery_status, cleanup.pending and cleanup.jobs include lookup-only work as
well as known provider jobs. Use known_pending and lookup_pending to distinguish
them; exhausted_pending also includes exhausted lookup jobs. A revoked session
with pending lookup has unresolved remote state even when known_pending is zero.
Zero total pending is not a provider deletion certificate or release acceptance.

No schema marker or recovery limit changes in this semantic update. Secondary
indexes are added, but existing v3 rows are retained. Stop/drain older application
binaries before rollout; v3 compatibility does not make the older unsafe result
path acceptable. Do not use an automatic old-binary restart as rollback. The
existing explicit v2-to-v3 migration and its unknown-historical-usage disclosure
remain in force. The tests are local fixtures; production/provider validation and
eligible independent review are still required.
