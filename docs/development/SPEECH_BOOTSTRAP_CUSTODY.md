# Speech bootstrap custody and revocation fencing

Status: HG-0087 speech source increment. Aggregate speech and HG-0087 remain OPEN.
Implementation: `services/model_gateway/speech.py`.
Regression: `services/model_gateway/test_speech_custody.py`.
Operations: `docs/operations/SPEECH_BOOTSTRAP_RUNBOOK.md`.

## Responsibility and trust boundary

`ProductionSpeechGateway` controls issuance and one-shot local consumption of a
short-lived speech provider bootstrap. It persists metadata only: subject/session,
generation, paired-device digest, locale, provider/ticket digests, expiry, state
and quota day. It does not persist bearer tokens, raw audio or transcript text.

The host supplies a trusted current Unix-seconds clock and a fixed
`provider_binding`. Callers can no longer choose `now` per request. A broker that
exposes `binding_id` must remain on that binding before mint/revoke calls. The
binding label is deployment configuration, not proof that a credential belongs
to a real provider account; authenticated tenancy is still external.

## State machine

A bootstrap is reserved in SQLite before broker work with state `minting`.
Reservation uses `BEGIN IMMEDIATE`, checks session revocation, rejects another
`minting`/`indeterminate` bootstrap for the same session, and charges the daily
subject issuance quota before any provider call. A process exit or broker error
therefore leaves durable recovery custody instead of making a second mint safe.

After the broker returns, the gateway validates an exact `ProviderSpeechTicket`:
HTTPS endpoint, bounded non-control bearer token, exact provider binding, bounded
provider ticket identifier, positive audio limit not exceeding local policy, and
an expiry strictly after current host time but not beyond the originally
requested expiry. It then reacquires the write transaction and rechecks local
revocation, reservation identity, broker binding and current expiry before
changing `minting` to `issued`.

`consume` checks bootstrap identity, session, generation and paired-device digest
inside a write transaction, rechecks `revoked_sessions`, requires `issued`, and
checks the host clock both before and immediately after marking consumed. A final
expiry error rolls the transaction back; a revoked session cannot consume an
otherwise valid bootstrap.

## Revocation race

The predecessor checked revocation only before the broker call and did not check
it in `consume`. A revoke that completed while ticket minting was blocked could
therefore be followed by a newly inserted `issued` bootstrap, which was then
consumable. The regression reproduces this with real SQLite and two threads.

The repair reserves first. `revoke_session` commits the local terminal revoke and
marks every reservation revoked before calling the broker. If a ticket returns
after that revoke, the bootstrap transaction keeps the row revoked and performs
one additional idempotent broker session revoke after mint completion, because
the earlier remote revoke may have raced ahead of creation of the late ticket.
The late ticket is never returned to the caller. If the second broker revoke
fails, `speech_remote_revoke_pending` is returned; local denial remains durable.
This is not independent proof of remote deletion.

## Failure and recovery

Broker failure or an invalid ticket after a committed reservation changes an
otherwise `minting` row to `indeterminate`. A new bootstrap for that session is
rejected with `speech_bootstrap_recovery_required` rather than replaying mint.
`pending_recovery(limit=100)` returns bounded distinct session IDs in `minting` or
`indeterminate` state for an authenticated operator path. Recovery currently
requires session-level revoke and provider facts; there is no automatic mint
readback or background worker.

The existing SQLite layout has no component version marker and this increment
does not claim a safe migration from arbitrary corrupted or rolled-back files.
Whole-database anti-rollback, encryption-at-rest, bounded retention and durable
remote revoke retry/outbox remain production work. Operators must stop/drain old
workers when deploying this API change because old binaries accept caller time
and do not understand the reservation states.

## Configuration and limits

`maximum_session_bytes` is 3,200..16,000,000; ticket TTL is 1..300 seconds;
subject daily bootstrap limit is 1..10,000; broker call deadline is in (0,60]
seconds. Identifiers use the existing bounded ASCII identifier grammar; locale is
1..64 alphanumeric/hyphen characters. Clock values are integer Unix seconds in
the supported timestamp range. Boolean values are rejected where Python would
otherwise treat them as integers.

## Verification and evidence ceiling

The new regression covers revoke-vs-mint concurrency, consumption after revoke,
host-clock expiry, removal of caller-controlled `now`, invalid ticket expiry,
provider-binding drift, atomic concurrent quota reservation and durable
indeterminate recovery. These are local source tests with a fixture broker.

This slice does **not** provide Android PCM-to-ASR, a live speech provider
exchange, authoritative mint/readback receipts, authenticated mobile identity,
stream lifecycle/finality, real credential revocation, privacy/retention
qualification, physical-device latency/accuracy evidence or independent
acceptance. Those remain OPEN under HG-0087 and product evidence gaps.
