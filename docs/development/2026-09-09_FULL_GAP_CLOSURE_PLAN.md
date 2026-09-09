# Full gap-closure execution plan — 2026-09-09

Status: active execution refinement for PR #114 and the G11 terminal-closure program.  
Scope: repository adoption plus all authority-owned product gates.  
Authority rule: the live pull-request head and Git tree are authoritative; a SHA copied into this document is never a substitute for live readback.

This document converts the productization roadmap and issues #82, #84–#96 and #102 into one dependency-ordered execution transaction. It does not weaken any existing contract, create external evidence, authorize self-review, or permit an administrator bypass.

## 1. Non-negotiable invariants

1. Never mark a gap closed from source code, issue checkboxes, screenshots, mocks, synthetic traces, repository-generated keys, or model-written receipts when the contract requires an external fact.
2. Never place private keys, access tokens, refresh tokens, signing material, raw audio, sensitive transcripts, personal pilot data, or proprietary firmware in source, pull requests, issues, Actions logs, or ordinary artifacts.
3. Every source movement invalidates prior exact-head CI, source artifact, review, prospective merge, and external-evidence binding for the successor.
4. The PR author or most recent source pusher cannot satisfy the required independent latest-head approval.
5. A timeout after a possible external or device effect remains indeterminate until authoritative readback or accepted reconciliation proves a terminal outcome.
6. The product release gate has no override. Every required authority class, artifact digest, signature, review, candidate identity, and acceptance context must validate together.

## 2. Starting state

The closure campaign starts from the source candidate formerly observed at PR #114 head `317ee1141ceac6df7d711aeaaca27b22d735e48d`, tree `51e673238d30b81ef8eb64b93eef14fc7bf850cb`. That object completed all seven source jobs and produced a verified source artifact, but it did not have an eligible `APPROVED` review and was not protected-main adopted.

This plan is intentionally prepared as a small successor change. Once committed, the predecessor CI, artifact, review state, and prospective merge are historical only. The new live head must complete the same exact-head qualification sequence before any promotion.

`main` remains the older baseline until canonical protection is applied and independently read back, followed by ordinary protected adoption.

## 3. Closure dependency graph

| Stage | Issues/gaps | Required outcome | Hard dependencies |
|---|---|---|---|
| C0 — source truth and execution control | source-side refinement | Current candidate identity is described truthfully; one closure DAG, control board, security policy, contribution protocol, and documentation-completeness standard exist | none |
| C1 — exact-head source qualification | #85 / HG-0044 source prerequisite | Seven non-empty jobs succeed on one unchanged head; source artifact is independently verified; an eligible non-author/non-latest-pusher Code Owner submits `APPROVED` | C0 |
| C2 — canonical repository policy | #84 / HG-0017 | All seven checks, strict mode, administrator enforcement, Code Owner/latest-push approval, stale-review dismissal, conversation resolution, linear history, and no bypass actor are applied and independently read back | C1; Administration-capable credential; independent API observer |
| C3 — protected adoption | #102 / HG-0089 | PR is merged only through the ordinary protected path; resulting exact `main` SHA receives fresh seven-job CI and independently verified artifact | C1, C2 |
| C4 — external trust root | #96 | Independently administered Ed25519 authority registry, proof of possession, narrow scopes, rotation/revocation policy, and out-of-band digest pin are operational | C3 preferred; may prepare roster before C3 but final bindings use adopted candidate |
| C5 — credential incident | #86 / HG-0013 | Historical credential is revoked provider-side; replacement is vault/KMS referenced; old credential fails a negative-use test; incident owner signs closure | C4 |
| C6 — identity and attestation | #88 / HG-0015 | Production KMS/HSM identities plus Android and Apple attestation are deployed, rotated, revoked, recovered, and evidenced | C4; final product identities |
| C7 — production providers | #87, #89, #90 / HG-0014, HG-0021, HG-0022 | Model, realtime, OAuth, Calendar and every enabled capability adapter use production tenants, minimum scopes, bounded authority, authoritative receipts, revoke, timeout reconciliation, retention and deletion controls | C4, C5, C6 |
| C8 — physical G1 and speech | #91, #92 / HG-0010, HG-0018 | Signed Android/iOS binaries pass declared physical handset/G1/firmware and locale matrices, including loss, reconnect, cancellation, stale fencing, latency, power, thermal and soak; speech uses the production boundary | C6, C7; signed test builds; physical lab |
| C9 — upstream and independent assurance | #93, #94 / HG-0011, HG-0016 | Vendor firmware/secure-boot/OTA/recovery authority and independent security/privacy/legal/accessibility/safety assurance approve the same unchanged candidate and evidence set | C4–C8 |
| C10 — release, pilot and distribution | #95 / HG-0012 | Production-signed binaries, binary SBOM/provenance/attestation, pilot, kill switch, rollback, staged rollout and store/distribution approvals are complete | C4–C9 |
| C11 — aggregate acceptance | #82 | Complete external bundle passes `--require-complete --require-accepted`; product release gate passes with no override; every child issue is closed from accepted evidence | C1–C10 |

## 4. Immediate repository work

The current source-side change must:

- correct `README.md`, `docs/CURRENT_STATE.md`, and `docs/PROJECT_STATE.json` so PR #114 is the live successor while PR #101 remains only the last independently qualified historical baseline;
- preserve `source_implemented` as the current successor maturity until exact-head CI, artifact verification and eligible review are all complete;
- publish this plan and `docs/operations/FULL_GAP_CLOSURE_CONTROL_BOARD.md`;
- publish `docs/development/MODULE_DOCUMENTATION_COMPLETENESS_STANDARD.md` so generated handoff pages cannot be mistaken for owner-authored implementation specifications;
- publish `.github/SECURITY.md` and `.github/CONTRIBUTING.md` without adding a disclosure channel or authority that does not exist;
- keep the canonical module-control generated sections byte-stable;
- run all seven jobs on the resulting exact head.

No source-side edit closes #84–#96 or #102 by itself.

## 5. Exact execution protocol

### 5.1 Freeze and qualify the source candidate

1. Stop unrelated source pushes.
2. Record the live PR number, base SHA, head SHA and tree from GitHub APIs.
3. Allow the canonical workflow to run all seven jobs on that exact head.
4. Verify every job is non-empty and terminal-success.
5. Download the source artifact twice through independent authenticated retrievals.
6. Verify ZIP safety, CRC, strict JSON, exact commit/tree, source-gate checks, history scan, native reports, SBOM, provenance and cross-digests.
7. Re-read the live PR head/base and review threads.
8. Obtain an eligible Code Owner `APPROVED` review bound to the exact head.
9. Any source/base/review-thread movement restarts this sequence.

### 5.2 Apply repository policy without bypass

From a trusted operator environment, use a short-lived Administration-capable credential that never enters source, chat, issues, logs or artifacts:

```bash
HEPTA_REPO_ADMIN_TOKEN='<provided only in the trusted operator environment>' \
python3 tools/repository_governance.py --apply
```

A distinct observer must then export a sanitized complete branch-protection and applicable-ruleset readback and validate every field against `contracts/main-branch-protection-v1.json`. The current managed GitHub App connection is not an Administration-capable channel.

### 5.3 Adopt through protected `main`

Merge only after C1 and C2 are simultaneously satisfied. Use the expected exact head and the ordinary protected path. Do not directly move `main`, invoke administrator bypass, relax policy, dismiss a valid objection, force-push, or delete branches to make the merge appear admissible.

After merge, run all seven jobs on the resulting exact `main` SHA and independently verify the new artifact. External evidence must bind to this adopted identity unless a contract explicitly requires an earlier subject.

### 5.4 Establish external authority

The independent registry controller must verify real identities, organizations, authority classes and proof of private-key possession before enrolling public keys. The registry digest must be distributed through a protected out-of-band channel. Evidence issuers cannot accept their own submissions; independent rows require organizational and operational separation.

### 5.5 Execute provider and physical work

Provider, KMS, attestation, OAuth, hardware, firmware, signing, pilot and store actions occur only in their real systems of record. Repository fixtures may test parsers and failure semantics but never become production receipts. Each artifact must bind the adopted source, exact binary/deployment/device/provider identity, environment, time interval, claims and limitations.

## 6. Parallel work rules

The following preparation may run in parallel before C3, provided final evidence is rebound after protected adoption:

- authority-seat identification and proof-of-possession scheduling;
- provider tenant and OAuth application design;
- physical-lab matrix, instrumentation and privacy-safe trace design;
- vendor authorization negotiation;
- independent assurance scoping;
- signing, pilot, rollback and store checklists.

The following cannot be accepted before the final candidate is frozen:

- exact-head source approval;
- branch-protection acceptance;
- production provider receipts represented as release evidence;
- physical reports bound to binaries;
- independent assurance approval;
- binary signing, pilot, rollout or store acceptance;
- final reviewer roster and aggregate acceptance.

## 7. Stop and reopen conditions

Stop promotion and reopen affected stages when any of these changes:

- source, base, workflow, contract, dependency lock, application identity or binary;
- provider tenant, region, model, OAuth registration, KMS key, attestation policy or deployment;
- handset, OS, G1 hardware, firmware, locale or lab method;
- trust-registry digest, key validity/revocation state, issuer roster or reviewer roster;
- unresolved high/critical assurance finding;
- failed revoke, recovery, kill-switch, rollback, pilot or store decision;
- artifact/signature digest mismatch or missing authoritative readback.

## 8. Definition of complete closure

“All gaps closed” means all of the following are simultaneously true:

1. No repository-actionable row is `OPEN`.
2. #84, #85 and #102 are satisfied by live GitHub policy, exact-head independent approval and ordinary protected adoption.
3. #96 supplies an independently administered out-of-band trust root.
4. #86–#95 contain authority-issued, digest-bound and independently accepted evidence for their exact subjects.
5. The complete external-evidence validator returns no missing gap, authority class, claim, artifact, signature, or review.
6. The product release gate passes without override for the unchanged adopted source and exact release binaries.
7. Parent #82 is closed only after all child evidence remains valid under a final live readback.

Until those conditions hold, the truthful state is source-implemented or source-qualified on the applicable axis, but product-blocked on the missing authority axes.
