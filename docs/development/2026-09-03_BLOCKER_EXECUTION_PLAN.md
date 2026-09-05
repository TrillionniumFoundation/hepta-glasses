# Active blocker execution plan

Revised: 2026-09-04  
Status: active remediation of the G8/G9/G10 candidate stack. This is not a new
G-number and is not a product-release claim. Continue on PR #101, fast-forward
only. Do not create parallel "final" branches, rewrite reviewed history,
self-approve, self-merge, or use administrator bypass.

## 1. Source identity and evidence rule

The live GitHub pull-request head and tree are authoritative; this document does
not freeze a hand-copied SHA. Every source change invalidates prior CI, artifact,
and review credit. After the final source push:

1. run all seven canonical jobs non-empty on one unchanged head;
2. independently download and verify the content-addressed source artifact;
3. bind every external-evidence candidate and review to that exact commit/tree;
4. obtain eligible non-pusher/CODEOWNER approval; and
5. adopt through protected `main` without bypass.

Historical G8/G9/G10 zero-open counts describe their scoped ledgers, not the
complete product. `docs/REMEDIATION_GAP_LEDGER.json` is the active repository
backlog. External facts are never promoted by changing source text.

## 2. Completed repository repair waves

| Wave | Source acceptance | Remaining authority |
|---|---|---|
| Inert historical fixtures | Exact Git blob/path/pattern/fingerprint custody; no test-directory exclusion | Exact-head CI and independent review |
| G10 evidence runtime | Absolute verified OpenSSL, sanitized environment, lexical no-follow custody, immutable signing transaction | Trusted verifier host and external registry administration |
| Reverse source ownership | Flattened 26-module registry, orphan/ambiguity/link/escape rejection, plugin registration | Maintainer ownership and final-head review |
| Capability uncertainty | Bounded duplicate waits/workers/receipts, post-dispatch indeterminate semantics, retained reconciliation failure | Durable provider state and live receipts |
| Memory consent | Serialized consent/read/write/export/revoke, narrowing deletion, bounded retention | Encrypted durable store and witnessed deletion |
| Module handoff | Validated module responsibility/API/state/failure/configuration/operations/platform/evidence mapping | Continuing owner review when APIs change |
| Trusted product gate | Product mode invokes G10 validation with an out-of-band registry pin and exact source identity; self-authored status fields have no authority | Complete signed E5–E7 package |
| Physical-trace integrity | Raw acquisition order is preserved; timestamp/capture-sequence drift fails; production scenarios require sample floors and fault observation/recovery | Real signed Android/iOS/G1 traces |

## 3. Remaining repository implementation: HG-0087

HG-0087 remains OPEN until implementation—not merely documentation—exists for:

- durable identity, device, session, token, and revocation repositories;
- KMS/HSM signing and Android/Apple attestation verifier interfaces;
- production model and realtime provider exchanges with cancellation, quota,
  retention, receipt, and revoke semantics;
- provider-specific OAuth capability adapters, durable idempotency/outbox,
  crash recovery, and authoritative readback;
- Android PCM-to-ASR and cross-platform speech privacy/finality integration;
- asymmetric Skill verification, package transparency, sandbox, egress policy,
  emergency revoke, and dependency evidence; and
- encrypted persistent Memory with per-subject keys, migration, backup exclusion,
  export/delete, and witnessed deletion.

Reference in-memory services, mocks, interface declarations, or unconfigured
fail-closed adapters do not close this row. Split implementation into reviewable
vertical slices, but keep one aggregate HG-0087 status until every named source
subtask passes its tests and operations contract.

## 4. GitHub administration and exact-head adoption

HG-0089/HG-0017/HG-0044 require actions outside source content:

- retarget or otherwise intentionally adopt the complete stacked candidate into
  the final `main` review path;
- apply all seven required contexts, strict mode, administrator enforcement,
  CODEOWNER and last-push approval, stale-review dismissal, conversation
  resolution, linear history, and disabled force-push/deletion;
- read every setting back through the GitHub API;
- freeze the source, run the full matrix, verify the artifact, resolve review
  conversations, and obtain an eligible latest-head approval.

The current connector may update source, issues, pull requests, workflows, and
refs, but cannot manufacture an independent approval or a repository setting it
cannot read/write. Keep these rows blocked until fresh API evidence exists.

## 5. External/provider/upstream waves

Retain HG-0010, HG-0011, HG-0012, HG-0013, HG-0014, HG-0015, HG-0016, HG-0018,
HG-0021, and HG-0022 until their actual authority-issued evidence is available.
Required work includes physical G1 labs, provider credential revocation,
production model/realtime/OAuth/capability tenants, KMS/HSM and attestation,
vendor firmware rights, Android/iOS speech, independent assurance, signed
binaries, pilot, rollout/rollback, kill switch, and store approval.

Every authority class signs only its exact claims. The final reviewer roster and
acceptance context are frozen and co-signed under the externally pinned G10 trust
registry. Do not create keys, issuer identities, provider receipts, lab traces,
reviews, signatures, pilot records, or store approvals to simulate closure.

## 6. Trusted product release acceptance

`tools/evaluate_release_gate.py --mode product` must:

- read the exact source artifact inputs;
- require canonical repository-relative external-evidence paths;
- obtain `HEPTA_EXTERNAL_TRUST_REGISTRY_SHA256` out of band;
- invoke `tools.external_evidence.validate_bundle` with current trusted time,
  `require_complete=true`, and `require_accepted=true`;
- verify repository/commit/tree identity, all twelve gap IDs, all issuer classes,
  final review-set integrity, and accepted closure; and
- reject legacy local `verified`/`approved`/`passed`/boolean fields as authority.

No product release proceeds until the resulting gate report has zero missing
checks. There is no override.

## 7. Validation after every source wave

Run repository, metadata, production-authority, source-coverage, and module-
handoff validators; all service/adapter tests and compile checks; Flutter format,
analyzer, and tests; both native platform lanes; ASAN/UBSAN and PCM parity; and
the all-ref history scan. The final report records executed commands, failures,
unexecuted gates, exact remote commit/tree, workflow run, artifact ID/digest, and
review state. Existing receipts never transfer across a push.
