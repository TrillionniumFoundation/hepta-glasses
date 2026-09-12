# Google Calendar single-event capability

Status: incremental source implementation for HG-0087/capabilities; aggregate OPEN.
Owner: capabilities. Source: `services/control_plane/google_calendar.py`.
Tests: `services/control_plane/test_google_calendar.py`.
Contract: `contracts/google-calendar-capability-v1.json`.
Operations: `docs/operations/GOOGLE_CALENDAR_CAPABILITY_RUNBOOK.md`.
This source packet must be committed and pass exact-head CI before source acceptance.

## Responsibility and API

This adapter implements Google Calendar API v3 event creation and exact-ID readback
for a single, explicit, operator-bound owned calendar. It is a concrete HTTPS
implementation, not a mock. Tests use local fixtures only; no real account or
calendar was accessed, and a working source path is not live provider qualification.
It does not provide OAuth consent/authorization-code exchange, refresh-token
storage, an HTTP service ingress, encrypted payload custody or a calendar UI.

`GoogleCalendarAdapter(subject, account_id, calendar_id, grant, clock)` is immutable.
The calendar ID must be concrete: the `primary` alias and path/query injection are
rejected. The identity/account/calendar/scope tuple and format profile determine
its `provider_id`. The scope is exactly `calendar.events.owned`, selected and
verified by the external trusted OAuth vault. The adapter refuses grants reporting
broader or different scope sets; this local field check is not token introspection.

The public capability is `calendar.event.create`, risk R2, mutating, with exactly
three fields: `title`, `start_at`, `end_at`. Start/end are absolute UTC epoch seconds,
not ambiguous local-time strings. The title is at most 256 characters / 1024 UTF-8
bytes, nonblank, without control characters. The duration is positive and at most
24 hours. All-day and recurring events, guest invitations, attachments, location,
description, conference data and arbitrary provider options are unsupported.

The generated event is private, confirmed and busy, with no attendee list and no
reminders. The request specifies `sendUpdates=none`; this does NOT establish that
Google will emit no account notifications or that every external calendar will
synchronize it. Those provider behaviors require real tenancy validation. This
profile is not appropriate for calendar migration or invitation workflows.

| API | Required caller behavior |
|---|---|
| `execute_authorized(request, operation_id, authorize=...)` | Gateway-owned only: reserved operation plus a live authority callback. Performs at most one POST. |
| `execute(...)` | Always rejects; prevents accidental use through an older gateway without final authorization revalidation. |
| `readback(request, operation_id, external_id)` | Requires fresh host-authorized readback access. Performs at most one GET of the derived event ID. |
| `provider_id`, `capability_spec` | Bind the exact trusted registration to this implementation; labels/risk cannot be silently replaced. |

A `CalendarAccessGrant` carries subject, Google account ID, calendar ID, operation
ID, request digest, purpose, exact scopes, expiry and access token. Its repr excludes
all fields. The grant callback receives only operation ID, bound digest and purpose;
it must authorize the currently authenticated requester before returning any token.
A dataclass from untrusted JSON is NOT proof of identity, ownership, scope or consent.
The opaque Google access token is ultimately validated by Google; actual account
binding must be verified by the external vault. Never put tokens in source or logs.

## State and concurrency

The existing `DurableCapabilityGateway` remains the sole durable dispatcher. Its
SQLite transaction writes the operation reservation, consumes the single-use lease
and writes the prepared event before external I/O. Duplicates return the existing
receipt across connections/restart; they do not call the adapter a second time.

An optional `execute_authorized` hook has been added to the gateway. After OAuth
retrieval and TLS connection establishment, the Calendar adapter invokes the
callback immediately before the mutation request. The callback reacquires the
SQLite transaction and checks the same operation fingerprint/state, persisted
subject revocation, original request deadline, consumed lease expiry and original
monotonic call deadline. Network work is never performed while this lock is held.
This closes the integration interval in which a slow vault/TLS operation could
otherwise outlive the initial lease check. Existing legacy adapters keep their
original execution path; they are not retroactively claimed to implement this hook.

The callback is trusted host code, not a portable authorization token or sandbox
boundary. An adversarial adapter can ignore a callback; arbitrary untrusted code
must not be registered in-process. Local admission is not atomic with Google's
receipt of a request. A revocation after network admission cannot cancel or erase
an effect that has already occurred; successful readback must remain truthful.

The OAuth grant expiry is checked on return, after TLS, and around final authority
validation. Time spent in the grant callback consumes the adapter's monotonic
transport budget. The enclosing bounded worker pool retains a timed-out worker's
permit until the actual worker exits. Thread limits are not process isolation,
remote cancellation or a global multi-instance quota.

## Provider request identity and readback

The event ID is `h` plus a SHA-256 digest of profile/provider/operation identity.
It fits Google's restricted ID alphabet and length. Its operation input includes
the gateway's UUID-derived random operation ID; it is not a user-selected event
path. The calendar stays fixed across retries. Private extended properties record
the operation ID, provider binding and argument digest. These hashes are metadata,
not a signature or an independently authenticated receipt.

A successful response/readback must match the event ID, requested title, actual
start/end instants, default event type, confirmed/private state, owner calendar,
absence of guests/recurrence/extra effects, disabled reminders and all binding
properties. Equivalent explicit timezone offsets are accepted; naive/all-day time,
unknown `-00:00` offsets, fractional drift, missing fields and mismatches are not.
A forged matching marker without matching event contents is insufficient.

The adapter reports `applied/terminal` only for that matched resource. This is an
observation of the desired effect at the trusted API boundary, not cryptographic
proof of authorship, a guarantee that nobody later edits the event, or independent
product evidence. Calendar owners/authorized writers can edit event metadata.

The adapter never asserts `terminal/not_applied`. HTTP 404/410, 409 collisions,
OAuth denial, throttling, server failure, malformed responses and changed/deleted
events remain unknown. Google documents that its distributed system does not
always detect event-ID collisions at creation. A fixed ID therefore helps correlate
readback; it is NOT a universal remote exactly-once guarantee and does not justify
repeated POSTs. The gateway's no-redispatch invariant remains essential.

## Failure and recovery

| Failure or observation | Outcome and continuation |
|---|---|
| No lease or wrong gateway registration | Denied before provider work; never install a permissive replacement lease. |
| Revocation/lease expiry during vault or TLS | No POST is admitted by this adapter; gateway retains a conservative unresolved receipt rather than granting automatic retry permission. |
| POST response lost, 409, 404 or server error | Indeterminate; reopen the original durable database and query the derived ID with GET. Never silently resubmit. |
| GET finds the exact matching event | Gateway records successful reconciliation without creating another event. |
| GET absent, altered, cancelled, unauthorized or malformed | Keep indeterminate. No overwrite, recreation, deletion or compensating mutation. |
| Original effect authority expired or was revoked | Mutation remains forbidden; separately authorized readback may still establish the historical result. |
| Readback budget exhausted | Escalate through the actual account/provider operator. Do not reset attempt counters or erase the operation ledger. |

Recovery needs the exact original `CapabilityRequest` from its authorized owner
or a separately designed encrypted payload store. The gateway persists metadata,
not plaintext arguments. This increment does NOT complete the encrypted outbox
requirement. Changing the provider/calendar/request/deadline under the old key
must fail as a binding conflict. Returning 404 is not permission to create a new
idempotency key with the same intended effect.

## Configuration and migration

The transport uses only `www.googleapis.com:443` and the Calendar v3 path, with
system certificate/hostname validation. It does not use environment proxies,
caller endpoints, redirects, OAuth refresh retries or automatic network retries.
The calendar path component is encoded; the event path component is derived.
No externally returned URL is followed. Per-call transport timeout defaults to
5 seconds and is finite within (0, 60]. The gateway independently caps its caller
wait/worker count. Responses are limited to 64 KiB and parsed without duplicate
JSON keys or nonfinite constants. Conflicting lengths/transfer encoding, compressed
responses, truncated bodies and ambiguous critical headers are rejected.

DNS, a noncooperative vault, HTTP header trickling or OS scheduling can exceed a
socket-level deadline. Bounded caller wait is not hard task termination. Production
requires bounded service replicas, egress governance, isolated workers and actual
provider-side rate/retention controls. Cleanup does not persist provider payloads;
cleanup exceptions are not reflected as user-visible private transport strings.

No database schema change is introduced by the authorization hook. No existing
operation/lease/revocation record is rewritten or automatically migrated. The
adapter binds a new named capability/route; trusted startup composition must
register the exact `SPEC` and `provider_id`. Existing unresolved operations must
continue using their original route; never relabel them to this calendar provider.
No credentials or mobile mutation authority are enabled by adding these files.

## Operations, verification, platform and evidence

Run the dedicated Calendar suite and existing durable-capability regressions,
then all repository and mobile/native CI checks on the actual final commit. New
tests exercise real SQLite, cross-connection revocation/duplicate races, OAuth
expiry, exact wire mapping and six real CPython HTTP parser tests over socketpairs.
Those socketpairs do not contact Google and are not TLS/provider qualification.
No real credential, personal calendar, event or user data is used in fixtures.

Required external dependencies include real authenticated consent/vault services,
Google-owned-calendar binding and token renewal/revocation, provider tenancy and
OAuth-app verification as applicable, encrypted recovery data, operational backup
and retention, production telemetry, and independent review. There is no OAuth
refresh endpoint, credential vault, mobile integration or remote compensation in
this package. The known separate identity enrollment defect and previously blocked
identity/speech/Memory packages are not repaired or republished here.

HG-0087/capabilities and the aggregate remain OPEN. Local tests do not certify a
published commit, protected-main adoption, an independent review or E5-E7 evidence.

### Primary references checked 2026-09-05

- Google Calendar Events.insert: https://developers.google.com/workspace/calendar/api/v3/reference/events/insert
- Google Calendar Events.get: https://developers.google.com/workspace/calendar/api/v3/reference/events/get
- Scope selection: https://developers.google.com/workspace/calendar/api/auth
- Extended properties: https://developers.google.com/workspace/calendar/api/guides/extended-properties
- Provider error semantics: https://developers.google.com/workspace/calendar/api/guides/errors

## Current-source integration checks

Responses marked `attendeesOmitted` or allowing arbitrary self-invitation remain
unknown even when the returned attendee list is empty. Malformed numeric timezone
offsets are rejected rather than normalized. Exact-byte cloud boundary policy
now registers only this transport and its wire regression file alongside the
existing model pair. The Calendar endpoint is prohibited in other scanned files;
static direct imports are confined to the control-plane service. No consumer
routing or runtime authorization is granted by the source declaration.

Incomplete existing capability schemas fail startup without recreating missing
denial or single-use lease state. Run the schema-integrity and Calendar boundary
regressions in addition to the original capability and Calendar suites.
