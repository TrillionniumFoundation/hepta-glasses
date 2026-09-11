# Model recovery inventory pagination

Status: incremental HG-0087/model source utility; aggregate and model slice remain
OPEN. Owner: ai-platform. Implementation:
`services/model_gateway/recovery_inventory.py`. Regression:
`services/model_gateway/test_recovery_inventory.py`. The durable request and
provider contracts remain in `docs/development/DURABLE_MODEL_GATEWAY.md` and
`contracts/durable-model-gateway-v2.json`.

## Problem and API

`ProductionModelGateway.recoverable(subject, limit=100)` is retained as a legacy
first-page metadata view. It cannot enumerate more than one page. Operators must
use:

```python
from services.model_gateway.recovery_inventory import recoverable_page

page = recoverable_page(gateway, subject="subject-id", after="", limit=100)
```

`ModelRecoveryPage.records` is an immutable tuple of `ModelReceipt` snapshots.
`next_after` is the final returned subject-scoped idempotency key only when the
same transaction observed another matching row. Pass that value as `after` for
the next page. Empty `after` starts a scan. Subject and cursor use the same
restricted identifier syntax; page size is 1..100.

Only `prepared` and `indeterminate` rows are returned. Committed and cancelled
rows are terminal and excluded. The helper does not call `generate` or
`reconcile`, reserve a claim, increment readback counters, extend authority,
return prompt/answer payloads, or create an execution permit. It uses the same
trusted local gateway database and receipt projection, so delivery-revoked state
reflects current local cancellation/session denial at the page transaction.

## Concurrency and completeness

Each page runs under one SQLite `BEGIN IMMEDIATE` transaction and is coherent with
admission for that page. A multi-page walk is not a global database snapshot.
Rows inserted with keys greater than the returned cursor can appear on later
pages. Rows inserted at or before a consumed cursor require a new scan from the
empty cursor. Rows may also become terminal between pages and disappear from the
pending view.

For a strict operational sweep, first quiesce new model admission for the subject,
walk until `next_after` is null, reconcile only through separately authenticated
recovery ingress, then rescan from the empty cursor before reopening admission.
Without quiescence, treat each walk as a bounded current inventory and periodically
restart it; never state that one pass proves no unresolved request exists.
Consumers should deduplicate by `(subject, idempotency_key, fingerprint)` when
combining repeated scans.

Cursor pagination is keyset-based rather than offset-based. Terminal removals or
insertions do not shift numeric offsets, and the database can use the existing
subject/idempotency primary key ordering. This does not make the scan an external
witness, distributed lock or multi-region snapshot.

## Failure and evidence boundary

Invalid subject, cursor or page size fails before database access. Storage errors
are returned; the helper does not silently skip a page or fabricate a terminal
state. A missing row between pages may have completed or been cancelled and must
be checked with the authenticated status path where appropriate.

Tests create more than 100 real SQLite request records, traverse all pages,
verify subject isolation and terminal exclusion, exercise concurrent insertion
semantics, and prove inventory reads do not consume claims/readback budget or
invoke a provider. Fixtures are not live tenancy, identity, retention, billing,
remote cancellation or provider recovery evidence.

HG-0087/model remains OPEN for authenticated service/mobile/session composition,
real tenant and retention qualification, authoritative remote recovery and
cancellation, process isolation/egress, encrypted metadata/backup anti-rollback,
production observability and independent acceptance. Keep PR #101 Draft and
require exact-head CI, artifact verification and eligible review.
