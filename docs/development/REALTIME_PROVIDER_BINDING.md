# Realtime provider namespace pinning and v4 storage

Status: incremental HG-0087/realtime source fix; aggregate OPEN. Owner: cloud.
Source: `services/control_plane/realtime_provider_binding.py` and
`services/control_plane/durable_realtime.py`. Contract:
`contracts/realtime-admission-v1.json`. Operations:
`docs/operations/REALTIME_ADMISSION_RUNBOOK.md`.

## Responsibility and integration with the current baseline

At parent 7ff0b7f0 the result-custody repair already preserves conflicting owned
remote sessions, rejects cross-session aliases without deleting someone else's
session, treats non-None revoke results as uncertainty, and reports lookup-only
cleanup. This increment preserves all of those behaviors and its 27 regressions.
It does not introduce a different quarantine state, suppress known cleanup,
reclassify conflicts or overwrite the newer baseline with an older candidate.

One remaining actual-code SQLite reproduction reopened a database populated by
fixture tenant A using fixture tenant B's adapter. B received A's remote session
ID for revoke and the local job became completed. The existing code's local
ownership checks cannot distinguish the same opaque ID in different provider
namespaces when the database has no persistent provider configuration binding.
This is a local configuration-error reproduction, not a live provider incident.

The v4 store binds its entire database to one non-secret operator-controlled
namespace. It rejects a differently configured reopening before any provider
work. New admission and provider-result acceptance also recheck the current
configuration, including after worker scheduling. It does not authenticate a
provider response, prove which account a credential belongs to, or provide an
execution sandbox. Real credentials and actual tenant mapping remain external
integration requirements.

## API and namespace definition

`DurableRealtimeStore(..., provider_binding=..., clock=...)` requires both an
explicit namespace and a trusted live host clock. There is no default namespace
and no automatic adoption of caller-supplied JSON. A binding is a 1..128-character
ASCII configuration identifier using letters, digits, underscore, dot, colon and
hyphen, beginning with a letter or digit. It is not a URL, token, credential or
free-form user content. Do not encode a secret or private account detail in it.

The deployment owner must bind that identifier to the actual provider, account,
project, region and lookup/revocation namespace. Changing any of those meanings
requires a different namespace and a separately designed service migration;
reusing the same string does not make a changed account equivalent. Credential
rotation may preserve the identifier only when its actual namespace is unchanged.

A trusted adapter may expose `binding_id`. When present it must be an exact string
match; None or another type is rejected. Exceptions from reading that property
are reduced to a fixed configuration error without private exception text.
Legacy trusted adapters may omit this property, but the host still MUST supply
an explicit reviewed `provider_binding`. Omitting a property is not a mechanism
for untrusted providers to choose authority; registration/composition is trusted
service code. Real integrations should expose an immutable declared namespace.

Public `provider` and `provider_binding` properties have no setters. This prevents
accidental replacement through the public API, not hostile modification of Python
private attributes or a malicious adapter lying about its credentials. The
provider implementation must keep its namespace stable for each call. Local
metadata checks cannot atomically control an external service under arbitrary
thread preemption or an adversarial host.

## Storage and current-operation checks

Storage version is 4. One new singleton table, `realtime_provider_scope`, stores
the explicit binding. New database creation stores it in the same initialization
transaction as the existing schema. Existing v4 databases reject a missing table,
missing/malformed singleton, wrong binding or wrong/unmarked component version;
there is no lazy refill, relabel or reset API.

The seven previous tables and their existing recovery policy/allowances remain
unchanged. Scope checks occur under the local lock or write transaction used by
current admission. Issuing/consuming tickets, returning active generation state,
activation workers, lookup workers, revoke workers, final activation commit and
cleanup acknowledgement cannot silently use another declared namespace.

A provider result that returns after its declared namespace changes is not
accepted as a new active state or completed cleanup. Existing request and attempt
custody remains for the correctly configured service to inspect. A namespace
change discovered after a recovery reservation does not refund its spent budget.
Network calls remain outside SQLite write transactions; checks do not hold a
database lock throughout provider I/O.

Local denial is deliberately separate from adapter health. With intact stored
scope, a local `revoke` can commit revoked state and pending cleanup even when the
adapter's declaration has drifted. Remote cleanup then fails closed; another
namespace is not called, and the pending job is not marked complete. Diagnostic
`recovery_status` remains available for that correctly scoped store. Active-state
replay and generation checks refuse a drifted adapter. A corrupted stored scope
or unavailable database is an operator incident; no durable success may be
claimed when state cannot be safely read/written.

## Compatibility: explicit offline v3-to-v4 migration

Normal v4 startup refuses v3. `migrate_realtime_v3(path, provider_binding=...)` is a
separate operator-only function. It opens an existing regular local WAL database
with SQLite `mode=rw`, not create, checks the exact v3 marker and all seven old
tables, validates recovery counters and database integrity, and checks historical
remote ownership before adding scope and advancing the marker in one transaction.

All old row values, original ticket deadlines, generations, remaining allowances
and spent recovery counters are preserved. The migration report explicitly sets
`historical_provider_verified=false`, `recovery_allowance_added=0` and
`independent_evidence=false`. Assigning a namespace does not prove historical
records were created in that tenant. Operators must establish that from genuine
provider/configuration records before migrating. Unknown actual ownership must
not be papered over with a convenient label.

Multiple remote cleanup IDs for ONE local session are valid retained conflict
custody and migrate unchanged. A remote ID claimed by DIFFERENT local sessions,
missing cleanup owner, malformed identifiers or a rebound cleanup key is rejected.
The helper does not pick an owner, delete an alternate job or reset budgets.
This is essential compatibility with the result-custody repair in 7ff0b7f0.

Failure rolls back the new table and version change, closes its connection, and
leaves the old rows intact. Missing files, symlink files, incomplete/unknown state,
invalid budgets and already-v4 state are rejected. There is no repeated migration
to change a binding. A v2 installation first follows the existing explicit
v2-to-v3 budget migration, including its unknown historical-usage disclosure,
then performs this v3-to-v4 binding step. The second step adds no new allowances.

Stop/drain all old processes and mutation ingress BEFORE migration. Reopened
v3 binaries reject v4; already-open old processes are not retroactively stopped.
No rolling upgrade, mixed-version execution or binary downgrade is qualified.
Migration is not a backup anti-rollback anchor, safe compaction, encryption or
proof of operational quiescence. Never downgrade a marker, edit scope, clear
old counters or restore an old snapshot to resume work.

## Validation and evidence boundary

Run `services.control_plane.test_realtime_provider_binding` together with all
five prior Realtime suites. The inherited 107 behavior tests remain, with explicit
fixture namespace construction and the v4 migration continuation where required;
no conflict or cleanup assertion is removed. The additional suite covers wrong
namespace reopening, read-only public configuration, scheduling/result-time drift,
local denial despite adapter failure, scope integrity, migration rollback and
actual subprocess exit after migration. Tests use real SQLite and inert providers,
not live credentials or external tenant evidence.

A separate integration probe uses the exact hash-verified 7ff0b7f0 implementation
to create a v3 database containing two pending owned cleanup IDs and spent lookup
and revoke budgets. After migration every value in its seven tables is compared;
the new code reopens it and the actual old constructor rejects v4. This is local
compatibility evidence, not a production migration drill.

Require full repository caller/import/ownership checks, all seven final-head CI
lanes, content verification of that head's artifact and eligible independent
review. HG-0087 remains OPEN for real provider/credential/tenant verification,
authenticated ingress, session lifetimes, production operational escalation,
provider facts, encrypted storage and independent acceptance. The known identity
verdict-freshness objection and previously blocked identity/speech/Memory/executor
changes are not repaired, retried or published by this independent increment.

Primary storage references checked 2026-09-05:
https://www.sqlite.org/lang_transaction.html
https://www.sqlite.org/uri.html
