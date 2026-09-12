# Full gap-closure control board

Status date: 2026-09-10
Parent control: issue #82  
Execution plan: `docs/development/2026-09-09_FULL_GAP_CLOSURE_PLAN.md`

This board is a coordination surface. It never replaces GitHub API state, provider records, physical measurements, vendor authorization, signatures, independent review, store decisions, or the canonical evidence validators.

Active source subject: the live head and Git tree of open PR #125 (`codex/hepta-identity-migration-20260910` into `codex/hepta-main-convergence-20260909-v2`). The board deliberately stores no copied current-head SHA; every execution re-reads GitHub before binding evidence or reviewer eligibility.

## 1. State vocabulary

| State | Meaning |
|---|---|
| `READY_SOURCE` | Repository preparation exists and the next action is source/review/CI work |
| `BLOCKED_ADMIN` | Requires a GitHub Administration-capable operator and independent readback |
| `BLOCKED_REVIEW` | Requires an eligible independent reviewer; author or latest pusher cannot satisfy it |
| `BLOCKED_EXTERNAL` | Requires a real provider, KMS, attestation, lab, assurance, signing, pilot or store authority |
| `BLOCKED_UPSTREAM` | Requires vendor or other upstream authority not owned by this repository |
| `ACCEPTED` | Canonical validation and required independent acceptance passed for the exact subject |

## 2. Live control board

| Order | Issue | Gap | Current state | Accountable execution role | Next non-substitutable action | Required acceptance object |
|---:|---:|---|---|---|---|---|
| 1 | #85 | HG-0044 | `BLOCKED_REVIEW` | eligible Code Owner independent of author/latest pusher | Review the complete current head and submit `APPROVED` bound to that exact commit after seven-job success | GitHub review plus signed external submission/acceptance under the active registry |
| 2 | #84 | HG-0017 | `BLOCKED_ADMIN` | repository administrator plus independent API observer | Apply the canonical protection payload with a short-lived Administration credential and capture a complete sanitized readback | accepted protection observation satisfying every contract field |
| 3 | #102 | HG-0089 | `BLOCKED_ADMIN` | repository administrator and merge operator | Merge only through the ordinary protected path with expected head, then qualify exact `main` | final `main` SHA/tree/run/artifact and independent verification |
| 4 | #96 | trust prerequisite | `BLOCKED_EXTERNAL` | independent release-security/assurance controller | Enroll real authority keys after identity and proof-of-possession checks; publish registry digest out of band | schema-valid registry, protected digest pin and witnessed negative/rotation drills |
| 5 | #86 | HG-0013 | `BLOCKED_EXTERNAL` | affected credential provider and incident owner | Revoke the historical credential provider-side, rotate through the production vault/KMS boundary and prove old-key failure | provider audit receipt, negative-use result and signed incident closure |
| 6 | #88 | HG-0015 | `BLOCKED_EXTERNAL` | KMS/HSM, Android and Apple attestation owners | Deploy production keys and attestation verification; exercise rotation, revoke, lost-device and recovery | authoritative key/attestation receipts and accepted drill package |
| 7 | #87 | HG-0014 | `BLOCKED_EXTERNAL` | model-provider tenant owner and cloud security | Qualify the production model tenant, retention, quotas, cancellation, revoke and redacted observability | provider/deployment receipts and independent acceptance |
| 8 | #89 | HG-0021 | `BLOCKED_EXTERNAL` | realtime tenant and OAuth registration owners | Register exact production apps/redirects/scopes; qualify one-time bootstrap, replay rejection, revoke and reconciliation | provider/OAuth exports and authoritative activation/revoke receipts |
| 9 | #90 | HG-0022 | `BLOCKED_EXTERNAL` | capability provider owners and privacy owner | Qualify each enabled adapter with minimum scopes, consent, single-use authority, receipts and readback | per-adapter provider evidence and privacy acceptance |
| 10 | #91 | HG-0010 | `BLOCKED_EXTERNAL` | physical device lab and mobile release owners | Execute signed Android/iOS plus physical G1 matrix with declared firmware and fault injection | `synthetic=false` signed reports passing the canonical SLO evaluator |
| 11 | #92 | HG-0018 | `BLOCKED_EXTERNAL` | speech-provider owner, mobile audio owner and physical lab | Run production Android/iOS speech, locale, finality, cancellation, privacy and latency matrices | production speech receipts plus signed physical reports |
| 12 | #94 | HG-0016 | `BLOCKED_UPSTREAM` | Even G1 firmware vendor or delegated authority | Supply written authority and execute secure-boot, OTA, interruption, recovery, rollback and key-revocation drills | signed vendor package accepted by independent assurance |
| 13 | #93 | HG-0011 | `BLOCKED_EXTERNAL` | organizationally independent assurance leads | Complete security, privacy, legal, accessibility and safety review of the unchanged candidate/evidence set | signed reports, findings disposition and independent approval |
| 14 | #95 | HG-0012 | `BLOCKED_EXTERNAL` | signing, release, pilot, rollback and store authorities | Produce production-signed binaries; execute pilot, kill switch, rollback, staged rollout and distribution approval | binary SBOM/provenance/attestation, pilot and store evidence |
| 15 | #82 | aggregate | blocked by children | closure controller plus final independent reviewers | Assemble the exact complete package and run all validators without override | accepted complete bundle and passing product release gate |

## 3. Connection and reviewer eligibility

Every repository operation must first re-read the live authenticated actor, current PR author, current most recent source pusher, requested reviewers and submitted review state. Capabilities and eligibility are facts of that exact transaction; they are not inferred from this document or from a previous operator session.

The managed GitHub App connection used by an operator may coordinate issues, create source branches and pull requests, request reviews, and perform ordinary repository writes allowed by its installation. The managed App class does not provide Repository Administration permission and therefore cannot read or apply the complete branch-protection contract. Repository-role `admin` and a conversational “highest permission” instruction do not change the installation token's granted scopes.

For every required independent approval, compare the live reviewer identity against the live PR author and most recent source pusher. Any actor matching a prohibited role is ineligible for that approval, regardless of repository role or conversational instruction. A later actor or source push requires a fresh eligibility readback. No operator may manufacture, submit on behalf of another person, dismiss or reinterpret an independent review to satisfy #85.

## 4. Daily closure transaction

Run this sequence for every active candidate day:

1. Re-read authenticated actor, PR head/base, author, most recent source pusher, review requests, submitted reviews and unresolved threads.
2. Re-read all seven workflow jobs and source artifact identity for the exact head.
3. Re-read public `main` protection and attempt the complete protected endpoint through the authorized observer channel.
4. Check the active out-of-band registry digest and key status.
5. Inventory every external submission, artifact digest, issuer class and reviewer decision.
6. Mark only newly authoritative facts; never copy a predecessor result forward.
7. Record blockers as one of: missing authority, missing artifact, failed validation, candidate drift, expired/revoked key, unresolved finding, or inaccessible administration.
8. Stop promotion immediately on any identity or evidence drift.

## 5. Handoff payload required from each authority

Every external owner must provide a package containing:

- exact repository, adopted source commit/tree and applicable release binary/deployment/device identity;
- issuer identity, organization, authority class, key ID, validity and permitted gap;
- canonical claims restricted to that authority's scope;
- artifact paths and SHA-256 digests;
- environment, time interval, result and explicit limitations;
- detached Ed25519 signature created outside repository custody;
- no secret, private key, raw audio, sensitive transcript, private device identifier or proprietary material not authorized for disclosure.

A later independent reviewer must sign an acceptance decision over the complete evidence-set digest, ordered reviewer roster and acceptance context.

## 6. Closure update rules

- Keep the GitHub issue open while any required item is absent, indeterminate, expired, superseded, or unaccepted.
- A comment may report progress but never changes the evidence state by itself.
- A checkbox may be selected only when its supporting authoritative object is linked or referenced by an immutable digest and accepted under the canonical validator.
- Close child issues before parent #82, and re-read all live identities immediately before aggregate closure.
- Reopen affected issues when source, binary, provider, device, firmware, registry, reviewer or policy identity changes.
