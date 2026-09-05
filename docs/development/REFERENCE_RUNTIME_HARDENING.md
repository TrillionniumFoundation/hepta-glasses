# Capability and Memory reference runtime hardening

Status: source implementation, not deployed production infrastructure. Owners:
capabilities and privacy. Contract: `contracts/capability-reference-v2.json`.
The G8/G9/G10 evidence contracts are unchanged; this guide supplements the central
module guide with the actual reference APIs and failure behavior introduced by
`2026-09-03_BLOCKER_EXECUTION_PLAN.md`.

## Capability interfaces

`CapabilityGateway(journal, clock, maximum_wait_seconds=30.0,
maximum_active_calls=4, maximum_receipts=4096)` registers typed `CapabilitySpec`
and `CapabilityAdapter` objects. `execute(request, lease=...)` returns a
`CapabilityReceipt`. There is no public HTTP route in this reference module.
An authenticated service layer must construct the subject/device/trust-class
fields and verify production leases; callers cannot assert authority themselves.

`CapabilityRequest` retains request/task/subject/device/name, arguments,
idempotency key, deadline, origin and optional exact confirmation digest.
Identifiers are nonempty strings <=256 characters, deadline is an integer and
origin must be a `TrustClass`. Arguments are copied through bounded strict JSON
before fingerprinting, lease validation or worker dispatch. The maximum encoded
argument size is 64 KiB; non-JSON values and non-finite numbers are rejected.
The private copy prevents concurrent caller mutation of admitted arguments.

A mutating lease must be exact subject/device/task/action/digest bound, unexpired,
and single-use. R3 requires the actual boolean `True` for biometric verification;
R4 remains unavailable. A string spelling a trust class is not a trusted enum.
The process-memory lease is a reference contract, not cryptographic attestation.

## State and concurrency

```
new -> request snapshot -> policy decision -> prepared journal -> consume lease
    -> bounded adapter worker -> completed journal -> retained receipt
                                       | timeout/error after dispatch
                                       v
                               indeterminate receipt
```

Identical keys/fingerprints join one owner or replay its retained receipt.
A different fingerprint conflicts. A duplicate wait is bounded by the request
remaining lifetime and configured wait ceiling; timeout never removes the owner.
The owner maps UTC remaining lifetime into a monotonic caller deadline.
The adapter budget also respects lease expiration. Completed/denied/uncertain
receipts are retained up to the configured limit; capacity exhaustion refuses
new work rather than evicting a key and permitting duplicate effects.

`BoundedCalls` uses at most `maximum_active_calls` daemon workers. A timed-out
worker keeps its semaphore permit until it really exits. Therefore a hung
provider cannot cause unbounded thread growth. A late successful worker cannot
overwrite an already returned indeterminate receipt. This is bounded caller
latency and worker count, NOT safe thread termination or a sandbox. Production
adapters require socket deadlines, cooperative cancellation and isolation.

## Capability outcomes

| Condition | Result | Replay/operational action |
|---|---|---|
| Invalid authority/schema | Denied or stable `CapabilityError` before adapter | Correct authority; no hidden dispatch |
| Worker capacity/deadline before start | `failed`, `retry_safe=true`, no possible effect | Existing key retains its receipt; a new attempt still needs new authority |
| Generic exception after mutating dispatch | `indeterminate`, `retry_safe=false` | Do not repeat the mutation |
| Adapter deadline after dispatch | `indeterminate` | Keep worker capacity occupied until completion; read back externally |
| Explicit uncertain external ID | Reconcile within the same bounded call | Success only for boolean authoritative receipt |
| Reconciliation exception | Retained `indeterminate`, external ID and error class | Repair readback; never infer non-commit from exception |
| Terminal audit write failure | `indeterminate` for mutations; completed sequence null | Retain receipt in memory and disable all NEW gateway work |

`completed_sequence` is now nullable: null is not an acknowledged terminal audit
record. This is a Python reference-v2 compatibility change, not a change to the
Dart transport's wire schema. Consumers must not format null as a persisted
sequence or convert indeterminate into failed/retryable.

The gateway cannot restore its in-memory receipts after process death. Durable
idempotency/preparation, an outbox, crash-window reconstruction, per-tenant quotas
and provider readback are still OPEN production work under HG-0087. Do not expose
this reference gateway directly to the internet.

## Memory interfaces and authorization

`MemoryStore(clock=..., id_factory=None, maximum_records=10000,
maximum_value_bytes=65536, maximum_consents=10000, maximum_audit_entries=4096)`
is still plaintext process memory. `grant_consent`, `remember`, `search`,
`export`, `delete`, `revoke_purpose` and `delete_all` preserve their public shapes.
Allowed classes match `memory-record.schema.json`: public, personal and sensitive.
Secret, credential, raw audio, unknown classes and boolean TTLs are rejected.
Trusted service ingress must authenticate subject; passing a string is not auth.

All consent/record/expiry/read/export/delete transitions share an RLock. A read or
export purges expired or no-longer-consented data first. Narrowing consent deletes
removed classes immediately and caps retained expiration to the shorter consent.
Renewal never resurrects data whose old consent expired. A generated ID collision
fails instead of overwriting another record. Capacity limits refuse new writes;
expired records can free capacity. The whole reference store is globally bounded,
not a deployed per-tenant quota service.

The metadata-only diagnostic ring is bounded and can evict old diagnostics. It is
NOT a durable or complete audit trail. Opt-out and deletion must remain possible
when that ring is full. Production must replace it with separately governed
audit export while preserving privacy deletion semantics. No prompts, values,
credentials or raw audio are emitted into this ring.

## Verification

```bash
python3 -m unittest services.control_plane.test_capabilities
python3 -m unittest services.control_plane.test_capability_boundaries
python3 -m unittest services.skills.test_memory
python3 -m unittest services.skills.test_memory_boundaries
```

New tests exercise bounded duplicate wait, uncertain post-dispatch error, late
success, retained worker permits, reconciliation failure, terminal-audit failure,
argument snapshot, malformed trust/single-use authority, no receipt eviction,
consent narrowing, TTL reduction, expiry/reconsent, identifier collision,
concurrent revoke/write, capacity and cross-subject deletion. Thread tests use
coordination events; local completion is not physical/provider evidence.

## Production handoff still required

Implement durable repositories and transaction boundaries before distributing
these services. Define backup recovery, key hierarchy, encrypted Memory, deletion
witnesses, tenant quotas, per-adapter cancellation/receipt contracts, KMS-backed
identity and emergency revoke. Add real provider integration tests and deployment
telemetry. The source patch closes scoped reference defects, not HG-0014/15/21/22
or the production-code backlog HG-0087.
