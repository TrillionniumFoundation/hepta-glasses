# P0–P3 operations and qualification handoff

Status: operator runbook for the source candidate, not an operated production
profile. Owners: release, ai-platform, cloud-security, privacy, device and the
accountable module owners in `docs/modules/modules.json`. No step below grants
its executor deployment, issuer, reviewer, signing or merge authority.

## 1. Freeze and inspect the actual source

Record repository, PR, head commit, tree, workflow ID/attempt, all seven job
conclusions and the exact source artifact identity from authenticated readback.
Preserve failure/skipped/cancelled distinctions. Never use a predecessor artifact
because its name is similar. The live branch/commit, not a copied document date,
selects the candidate. Source movement requires fresh qualification.

Flutter package authorization failure: compare the pinned Flutter version,
committed lockfile, intended package hosts, runner network and authorized package
configuration. Do not print credential files or the full environment, install an
untrusted mirror, purge evidence, or disable lockfile enforcement. An exact-head
re-run after a diagnosed external transient is allowed; repeating tests until a
failure disappears is not a replacement for diagnosis.

iOS failure: preserve the selected simulator UDID/runtime, source test inventory,
first failing or stalled selector, xcodebuild exit, and xcresult. A build pass is
not a test pass. The checked profile requires explicit counts, no skips and the
same number of tests as the current RunnerTests source. Test timeouts remain
failures. Do not delete a random-input case or make it vacuously pass.

## 2. Read capacity without rewriting authority

Run only on a trusted host with operator access to its approved local database:

```bash
python3 -m services.qualification.model_capacity \
  --database /srv/hepta/state/model.sqlite --timeout-seconds 2
```

The path is an example of an operator-owned location, not a file supplied or
created by the repository. Relative paths, linked paths, absent files, unknown
schema versions and incomplete authority tables are rejected. SQLite is opened
with `mode=ro`, query-only mode and a bounded progress handler. No transaction
writes or checkpoints are issued. Normal SQLite WAL shared-memory/read-sidecar
behavior can still occur; do not claim total filesystem immutability. The local
filesystem and SQLite runtime are trusted dependencies, not hostile inputs.

The report contains only aggregate counts, persisted limits, diagnostic levels,
suspension and exhausted unresolved readbacks. It deliberately sets both
`admission_authority=false` and `release_authority=false`. It is not a liveness,
identity, provider-billing, confidentiality or production-readiness certificate.
Keep even aggregate telemetry access-controlled. Never attach the database,
subject IDs, provider IDs, prompt hashes, raw audio, request payloads, bearer
credentials or decrypted exports to a public support ticket.

| Observation | Required response | Forbidden shortcut |
|---|---|---|
| 80% request/denial capacity | Notify owning operator, forecast exhaustion from measured arrival rate and plan reviewed migration | Assume the daily quota is a lifetime-storage limit |
| 95% capacity | Prepare controlled admission reduction and a reviewed continuity plan | Raise persisted policy on reopen without migration |
| Exhaustion or persistent suspension | Preserve state; stop accepting work where the owning gateway denies it | Delete requests/tombstones, replace the database, reset suspension or refund attempts |
| Unresolved readback budget exhausted | Escalate exact uncertain custody through the authenticated host/provider route | Create a new generation or idempotency key to hide the old uncertainty |
| Probe failure | Treat operational visibility as unavailable and investigate storage/schema/permissions | Report zero use, healthy state or restored authority |

The model gateway's default lifetime capacity is 4,096 request rows. At an
assumed 1,000 new requests per day without safe archival, it is exhausted during
the fifth day. This is arithmetic for planning, not a measured throughput claim.
Use actual workload, denial growth and event growth to plan operation. This
increment intentionally supplies no unsafe archival/reset implementation.

## 3. Uncertain effect recovery

Preserve original subject/session/device/provider namespace, idempotency identity,
argument digest, authority expiry, generation and every denial. Authenticate the
recovery caller again. Inventory unresolved work through the owning component's
bounded status/readback interfaces; do not query unrelated tenants or issue a
new effect under an old decision.

For the foreground nonstored model-provider profile, correlation is not an
answer lookup service. A lost answer may remain indeterminate. Local cancel
suppresses delivery; it does not prove remote termination, deletion or refund.
Capability readback needs the authorized original request or a separately
approved encrypted payload store. Loss of that payload is a product recovery
blocker, not permission to persist plaintext in ordinary logs or resend blindly.

For G1, preserve pair/generation/side/command custody. An accepted prefix or
one-leg success cannot be converted into a clean failure. Use only documented
authoritative reconciliation or retirement of the relevant generation before a
new authorized action. Do not use serial-number/liveness/CRC replies as general
mutated-state readback when the command matrix says it is unavailable.

Required drill records distinguish: no effect admitted; effect may have occurred;
bound authoritative completion; local denial; remote cleanup pending; readback
exhausted; operator escalation. Each record binds its actual environment and
candidate. A fixture-effect marker proves only the fixture scenario.

## 4. Backup, migration and anti-rollback

Stop admission and drain/terminate old workers using the reviewed deployment
controller before an offline migration. A caller timeout does not stop a Python
worker, a socket exchange or remote provider work. Record unresolved custody
before changing storage. Do not run mixed versions when the component prohibits
it, and do not extend persisted authority expiry during migration.

The current source profiles include model v2, realtime v4, durable capability v2,
identity v1, signed-Skills v1 and Memory layout v1. Consult each primary document
and its migration tool before touching a real store. A schema marker is not an
external anti-rollback anchor. Startup integrity checks cannot prove that an
entire restored file is the newest authorized state.

No production restore is qualified until its owner has demonstrated preservation
of consumed leases, idempotency identities, revocations, pending effects, recovery
budgets and deletion-propagation facts. An externally administered monotonic
anchor/restore authorization and reviewed encrypted backup topology remain open.
Never restore a stale snapshot just to recover service availability.

For Memory, use a real per-subject authenticated cipher/key service and an
approved export/delete path. SQLite secure deletion is not evidence that WAL,
snapshots, replicas, backups or providers removed data. Downstream deletion
acknowledgement requires genuine downstream facts. Key loss, compromised-key
rotation and deletion during clock-service failure each need a witnessed drill.
Do not promote the repository fixture cipher or local tombstone into that proof.

## 5. End-to-end operational acceptance

| Drill | Required invariant | Scope that must be measured |
|---|---|---|
| Revoke during credential acquisition/TLS | No new permitted prompt/effect after the component's final denial check; late results cannot regain authority | Actual host/provider composition, not only adapter unit tests |
| Expire while queued or holding a database lock | No refreshed authority from the old request-arrival time | Wall/monotonic clock handling and lock/caller budgets |
| Kill after durable prepare, before/after send | Durable uncertainty survives; no automatic second effect | Process exit and remote readback with actual deployment storage |
| Lose one BLE leg after the other succeeds | Pair receipt remains degraded/unknown | Both actual devices and declared firmware |
| App background/relaunch while audio/model/page is pending | Old generations do not publish; history remains default-off | Supported OS/device/locale and permission/interruption cases |
| Capacity exhaustion and recovery budget exhaustion | Denial and unresolved custody remain; operator escalation works | Sustained load and real alerts, not a manually edited healthy report |
| Account/subject deletion and backup restore | Deleted/revoked authority cannot reappear | KMS, backups, replicas and propagation receipts |

Observe privacy-safe error codes, stage latency, queue depth, in-flight workers,
capacity growth, uncertain-effect counts, cleanup age and revocation propagation.
No raw content belongs in metric labels. Define actual alert routing and on-call
ownership before declaring operational qualification. No exporter or paging
integration is installed by the capacity observer.

## 6. Physical and external qualification packet

Use `docs/EXTERNAL_CLOSURE_PROGRAM.json`, `contracts/qualification-slo-v1.json`,
the device qualification runbook, and the existing G9/G10 authenticated evidence
pipeline. This checklist does not supersede any of them.

Before collection, freeze application source and binary identities, signing
identity, OS/device model, left/right G1 identity, firmware, provider profile,
operator/lab identity and measurement tooling. Obtain real consent and minimize
trace content. Preserve raw acquisition order, monotonic timestamps and complete
capture sequence when present. Record both fault injection and observation plus
recovery; do not sort traces later to conceal causal order.

The current qualification contract (version 2) requires at least 3,600 seconds of
collection, 30 wake-to-listening and 30 end-of-speech-to-first-display samples,
1,000 packet samples per side, and 12 battery and 12 temperature samples. Its
limits are wake-to-listening p95 <=300 ms, end-of-speech-to-first-display p95
<=3,500 ms, packet loss <=1%, temperature <=42 C, zero duplicate effects and end
battery >=10%. These are existing acceptance thresholds, not measurements achieved
by this change. Consult the unchanged contract if any copied value disagrees.

Run the required faults on both supported mobile-platform profiles:
left disconnect, right disconnect, dual disconnect, network handoff, token expiry,
model timeout, application restart, user cancellation before effect, and an
external effect completing after local timeout. Add locale/background/permission,
power/thermal and firmware-specific cases required by the accountable owners.
Unsupported Android production ASR remains a blocker rather than a synthetic pass.

| Existing gap | Real issuing/acceptance dependency |
|---|---|
| HG-0010 | physical Android/iOS G1 lab reports and declared firmware/device custody |
| HG-0011 | independent security, privacy, legal, accessibility and safety assurance |
| HG-0012 | actual binary signing, pilot, staged rollout, kill-switch, rollback and stores |
| HG-0013 | provider-side credential revocation/rotation and incident-owner closure |
| HG-0014 | real model tenant, retention/billing controls and accepted provider receipts |
| HG-0015 | operated KMS/HSM and Android/Apple attestation verification |
| HG-0016 | firmware vendor command/version/signing/recovery authority |
| HG-0017 | live administrator settings plus authenticated API readback |
| HG-0018 | real Android ASR composition and physical iOS speech qualification |
| HG-0021 | real realtime/OAuth provider and remote-cleanup qualification |
| HG-0022 | each enabled capability provider, scoped consent and authoritative recovery |
| HG-0044 | eligible independent unchanged-head source review |

Evidence issuers and reviewers must own their authority outside the feature
branch. The expected trust-registry pin must arrive out of band. Required
multi-authority seats, claim partition, signature preimages, reviewer independence
and aggregate acceptance remain enforced by the existing verifier. Neither a
repository-written identity nor this runbook can satisfy them.

## 7. Promotion and rollback decision

A green source matrix permits source review, not production rollout. Promotion
requires the exact source and binary, accepted external evidence, qualified
operators, incident closure and real distribution approvals. Keep evidence and
review roles separate from implementation. On any unsupported integration,
missing external fact, unresolved effect, failed drill or candidate movement,
retain the blocked state and its concrete owner/unblock condition. Never relax
branch protection, self-approve, self-merge or use an override release path.
