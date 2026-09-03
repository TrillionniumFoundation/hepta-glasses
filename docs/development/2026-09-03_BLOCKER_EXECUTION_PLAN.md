# 2026-09-03 blocker execution plan

Status: active remediation of the G8/G9/G10 candidate stack. This is not a new
G-number or a product-release claim. Continue on PR #101; do not create parallel
"final" branches, rewrite reviewed history, self-approve or self-merge.

## Authority and preservation

The inspected starting head is e8593d6a23405ad0f83f63faf171a96b92ac3626,
tree 395ddd872044c7e4564dbb38cc2a85e37568faaf. Before publication read the live PR
head again; fast-forward only. A changed base/head requires a new qualification.
The canonical G8 product plan and G9/G10 evidence contracts remain in force.
Their zero-open counts describe their historical scoped ledgers, not the entire
product or this new remediation backlog. No external row is silently promoted.

## Implementation sequence and acceptance

| Work | Owner | Required source acceptance | Remaining authority |
|---|---|---|---|
| Invalid key-shaped test fixture | release-security | Reject symlink before parsing using inert bytes; retain the hostile test | Exact-head CI |
| Historical fixture custody | release-security | Acknowledge only the exact historical Git blob, path, pattern and fingerprint; changed blobs fail; no test-directory exclusion | Independent review |
| G10 metadata drift | architecture | Restore tested scope/ceiling statements and add typed validation_controls; preserve every signature/security rule | Exact-head CI |
| Reverse source ownership | architecture | Flatten G8/G9/G10 plus explicitly registered additions; unknown source paths fail; conflicts resolve explicitly; plugin covered | CODEOWNER assignment by maintainers |
| Capability uncertainty/deadline | capabilities | No unbounded duplicate waits; post-dispatch exceptions become indeterminate; reconciliation failures retain a receipt; timeout never authorizes replay | Durable storage, live provider receipts |
| Memory consent consistency | privacy | Atomic consent/write/revoke; read/export respect current consent; narrower consent removes inaccessible records; bounded retention | Encrypted durable store and deletion drills |
| Current-state projection | repository-governance | Derive module/gap counts and immutable source identity; do not commit self-attesting CI success or overwrite historical evidence | GitHub job/artifact/review readback |
| Module-local engineering docs | owners | Actual interfaces, state transitions, errors, concurrency, tests and operational limits; length is not completeness | Production configurations remain separately reviewed |

## P0 publication

Use one atomic tree per repair package. Keep the seven canonical checks, history
scan, signature verification, source artifact gate and independent-review rule.
A PEM-header fingerprint alone is not a safe exception because all keys share
that header. New private-key fixture acknowledgements must also pin the complete
Git blob ID. This acknowledgement covers an invalid historical sentinel only;
it is never credential revocation evidence for HG-0013.

## Product work remains implementation work, not merely missing paperwork

Production identity requires persistent device/revocation repositories, KMS/HSM
and attestation verifiers. Realtime requires a real provider exchange and scoped
sessions. Capabilities require per-provider consent, credential handles, durable
idempotency, outbox/recovery and readback. Android requires a PCM-to-ASR adapter.
Skills require asymmetric verification and a deployed sandbox. Memory requires
encrypted storage, per-subject keys and deletion/backup semantics. Those source
subtasks must be tracked OPEN until implemented; accounts and witnesses do not
substitute for code. No deterministic reference is labelled production-ready.

## External/admin/upstream acceptance

Retain HG-0010, HG-0011, HG-0012, HG-0013, HG-0014, HG-0015, HG-0016, HG-0017,
HG-0018, HG-0021, HG-0022 and HG-0044 until their actual contract evidence is
available. This includes physical G1 traces, provider credential revocation,
live model/realtime/OAuth adapters, KMS/HSM and attestation, vendor firmware
rights, independent assurance, complete protection readback, final-head review,
signed binaries, pilot, rollout/rollback and store approval. Do not create keys,
issuer identities, lab traces or approvals to manufacture these facts.

## Validation and evidence record

Run the three repository validators, all service/adapter tests, compile checks,
Flutter, both native lanes, sanitizers and all-ref history scan. Local tests of
reconstructed fetched files are scoped local results, not a full checkout run.
The final report records actual commands, failures, unexecuted gates and the
exact remote commit. Existing success receipts never transfer across a push.
