# Calendar capability operating and recovery runbook

Owner: capabilities. Scope: single owned-calendar event creation and readback.
Design: `docs/development/GOOGLE_CALENDAR_CAPABILITY.md`.
Contract: `contracts/google-calendar-capability-v1.json`. HG-0087 stays OPEN.

## Preconditions

Keep this route disabled in consumer ingress until actual account authentication,
cryptographic decision-lease verification, OAuth consent, token-vault ownership
checks and revocation consumers are qualified. A local dataclass is not an OAuth
proof. Bind an explicit owned calendar ID, the Google account ID and local subject
at trusted startup. Do not use `primary`, package-supplied routes, or a credential
from another account. The granted scope must be exactly calendar.events.owned.
Validate real provider scope requirements and OAuth-app verification separately.

Use operator-owned local SQLite storage, a restricted service account and umask
077. Operational storage encryption, backup restrictions and anti-rollback state
are external requirements. Do not drop old request/lease/revocation rows or restore
a stale snapshot to clear capacity. The metadata ledger is not an encrypted outbox.

Register the immutable adapter's own capability_spec and provider_id. The gateway
rejects mismatched labels and risk contracts. Do not invoke its legacy execute
method or substitute an always-allow authorization callback. Only trusted service
code may register adapters or construct leases. No untrusted plugin runs in this
process, and no Skill/model output is execution authority.

## Execute and observe

Build a request for `calendar.event.create` with title and absolute epoch-second
start/end. The host owns timezone conversion and user confirmation of the precise
calendar/time/title. A single-use lease must bind that exact argument digest.
The API profile creates one ordinary, private, busy event, without guests or
reminders. It is not an invitation, recurrence, migration or calendar-clearing API.
Provider notification behavior still needs real tenant verification.

The gateway reserves and journals before the POST. The adapter fetches a bounded,
operation-bound OAuth grant, establishes TLS, then invokes the gateway's current
lease/revocation check before sending. Monitor safe outcome codes and aggregate
counts; never log grants, tokens, response bodies, titles or original calendar IDs.
Opaque operation/event hashes still require access controls and retention policy.

## Recover without duplicate events

After a timeout/crash, preserve the original database and exact request. A repeated
gateway execute returns the stored receipt; it must not recreate the event. Query
pending operations and use `gateway.reconcile(original_request)` with separately
authorized readback access to the same account/calendar. The adapter uses GET on
the deterministic event ID; it never changes to another provider, creates a new
ID or compensates by deleting something.

If GET matches all requested fields and binding markers, record reconciliation.
Missing, cancelled, changed, unauthorized or conflicting resources stay unresolved.
404 and 409 are not proof of no effect. Investigate through the real provider and
account operator. Never change `unknown` to `failed/retry_safe` merely to unblock
an interface, or create a replacement event under a new key without fresh user
intent and actual investigation of the old operation.

A local revoke before POST blocks this route. A revoke after the provider accepted
an event cannot undo it. Do not falsify a successful historical effect or pretend
a token expiry deleted a calendar resource. Deletion/cancellation needs a separate
explicit user-authorized operation and contract, not an implicit rollback here.

## Resource and security incidents

Vault/transport hangs consume a bounded worker slot; a caller timeout does not kill
that worker or remotely revoke a token. Stop new admissions during saturation and
use the deployment's process-isolation and incident controls. Do not create more
gateway objects to escape per-instance limits. Drain workers before closing storage.
Google 401/403 must trigger real credential-owner investigation; this adapter does
not obtain refresh tokens or silently broaden permissions.

Changed calendar/account configuration changes provider_id and invalidates old
bindings. Do not migrate unresolved operations onto a different calendar, rewrite
markers or fabricate a provider receipt. Preserve evidence from the real provider
without retaining private response bodies in routine diagnostics.

## Verification and acceptance

```bash
python3 -m unittest services.control_plane.test_google_calendar \
  services.control_plane.test_durable_capabilities -v
python3 tools/validate_repository.py
python3 tools/validate_repository_metadata.py
python3 tools/validate_production_authority.py
python3 tools/validate_source_coverage.py
python3 tools/validate_module_handoff.py
python3 -m unittest discover -s services -p 'test_*.py'
python3 -m unittest discover -s adapters -p 'test_*.py'
python3 -m compileall -q services adapters tools
```

Require all seven exact-head CI lanes and downloaded artifact verification after
publication. Socketpair/wire fixtures prove parser behavior only, not Google TLS,
OAuth verification, actual account ownership, provider retention or live recovery.
Obtain independent review and real provider/device/product acceptance separately.
Do not self-approve, self-merge, weaken protection, release or enable consumer
mutations to convert missing acceptance into a green status.
