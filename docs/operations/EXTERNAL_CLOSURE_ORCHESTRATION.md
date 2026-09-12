# External authority closure orchestration

Status: canonical operator workflow for Administration, provider, device, firmware, assurance, signing, pilot, rollout, rollback, store, and release evidence. This runbook does not declare any gate closed merely because source preparation, an issue, a template, or a validator exists.

## 1. Scope and non-negotiable boundary

`docs/EXTERNAL_CLOSURE_PROGRAM.json` is the machine-readable inventory of every remaining non-source gate. It maps the current GitHub issues to an authority class, evidence requirements, acceptance rules, prohibited substitutes, and reopening conditions. `tools/validate_external_closure_program.py` validates that the inventory is complete, closed-world, path-safe, and honest about its blocked status.

The repository cannot issue its own external authority. A maintainer, model, workflow, administrator, or test fixture may prepare schemas, clients, runbooks, evaluators, and evidence envelopes, but cannot impersonate a provider, KMS/HSM operator, platform-attestation provider, physical laboratory, firmware vendor, independent reviewer, signing authority, pilot operator, rollback owner, or store.

## 2. Candidate freeze and identity ledger

Before collecting any external evidence, record one immutable candidate ledger containing:

- repository and pull-request identity;
- base commit, head commit, head tree, and prospective merge identity;
- canonical workflow ID, run ID, run attempt, and all seven job conclusions;
- exact-head source Artifact ID, name, byte length, ZIP SHA-256, and verified member inventory;
- module-registry digest, release-version contract, dependency locks, source SBOM, provenance, history report, and native-sanitizer report;
- Android and iOS application identities, source version, build numbers, entitlement or permission set, and eventual signed binary digests;
- production deployment, provider tenant, KMS/HSM key, OAuth registration, firmware, physical-device, trust-registry, reviewer-set, pilot, rollout, rollback, and store identities as those become available.

Every evidence package must name this ledger and bind the applicable identities directly. Source, base, workflow, dependency, contract, toolchain, application identity, signer, entitlement, provider, KMS/HSM, OAuth, firmware, device, laboratory, trust registry, reviewer roster, policy, pilot, rollout, rollback, or store movement reopens the affected gate. Never edit an accepted packet in place; create a successor package with a new content address and new signatures.

## 3. Wave A — repository governance and independent trust

### 3.1 Canonical `main` protection

An Administration-capable operator applies `contracts/main-branch-protection-v1.json` through the reviewed `tools/repository_governance.py` path. The credential is short-lived, least-privileged, and never enters source, Actions, issues, pull requests, artifacts, screenshots, or logs. A distinct observer performs a full read-only API query and preserves a sanitized payload proving all seven exact checks, strict status evaluation, administrator enforcement, Code Owner and most-recent-push review, stale-review dismissal, conversation resolution, linear history, force-push/deletion denial, and absence of a bypass actor.

Only after that readback is independently accepted may the convergence PR leave Draft. Adoption occurs through the ordinary protected merge path. Direct `main` ref movement, administrator bypass, temporary policy weakening, synthetic statuses, or approval dismissal are prohibited. The resulting exact `main` SHA then receives a fresh seven-job run and independently verified Artifact.

### 3.2 Out-of-band authority registry

An independent release-security or assurance controller creates the Ed25519 authority registry outside repository and evidence-package custody. Every enrolled public key is bound to a verified legal or organizational identity, narrow authority class, allowed gap set, validity interval, proof of possession, and separation rules. The controller distributes the authoritative registry SHA-256 through a protected out-of-band channel.

Run expiry, wrong-key, duplicate-key, alias, same-SPKI, cross-class, revoked-key, substituted-registry, path-replacement, malformed-PEM, signature, timestamp, reviewer-set, and acceptance-context negative tests. Witness at least one rotation and revocation drill. No private key may enter GitHub or the evidence package.

### 3.3 Authenticated independent review

After the final source head is stable and its Artifact is verified, an eligible Code Owner who is neither author nor latest pusher submits a fresh exact-head GitHub approval. A separately controlled reviewer key signs a statement binding repository, base, head, tree, prospective merge, workflow run, Artifact, digest, GitHub review ID, review timestamp, reviewer identity, and resolved-conversation state. A distinct later acceptance reviewer signs the ordered final reviewer roster and acceptance context.

## 4. Wave B — credential, identity, providers, and capabilities

### 4.1 Historical credential incident

The affected provider revokes the historical credential by provider-side identifier and issues an authoritative receipt and timestamp. The incident owner records a negative-use result, replacement opaque KID or secret-manager reference, revised scope and policy, forensic timeline, findings, and closure approval. Never attach the old or replacement credential.

### 4.2 Production identity and KMS/HSM

Deploy non-exportable production identities in KMS or HSM. Capture opaque KIDs, algorithms, region, tenancy, policy digests, rotation overlap, retirement, revocation, lost-device containment, recovery, and audit receipts. Integrate Android and Apple attestation with nonce or challenge binding, application and signer identity, device key, freshness, replay rejection, and verdict policy. Simulators and software-only mock keys do not qualify.

### 4.3 Production model provider

Deploy the declared production model tenant behind the server boundary. Configure model, deployment, region, quota, rate, abuse controls, retention, training-use policy, deadline propagation, cancellation, revocation, and privacy-safe observability. Execute live success, rejection, timeout, cancellation, quota, provider failure, revoke, and reconciliation cases. Receipts must bind the exact tenant, deployment, policy, source candidate, and service identity.

### 4.4 Production realtime and OAuth

Register exact Android and iOS identities, redirects, origins, and minimum OAuth scopes. Provider secrets and refresh tokens remain server-side. Exercise one-time bootstrap issuance and atomic consumption, replay, wrong device, wrong scope, stale and expired tickets, provider activation uncertainty, reconciliation, revoke, and termination. A successful WebSocket without authoritative tenant and revoke receipts is insufficient.

### 4.5 Capability adapters

For every adapter enabled in the production profile, record provider registration, minimum scopes, direct user consent, purpose, opaque credential handle, policy, exact lease, external receipt, duplicate coalescing, argument-drift rejection, uncertain-effect reconciliation, revoke, retention, export, deletion, and redaction. Disabled adapters remain unavailable and need no synthetic passing evidence.

## 5. Wave C — physical G1 and speech qualification

Freeze signed Android/iOS build digests, handset and OS matrix, G1 left/right opaque test identifiers, hardware revisions, firmware versions, locale, permissions, RF environment, instrumentation, scenario, clock, operator, and laboratory identity before collection.

Use acquisition-order JSONL traces and the canonical evaluator. Evidence must set `synthetic=false`. Qualify dual-leg authority, protocol framing, sequence and generation fencing, malformed input, delayed or missing ACK, duplicate and late responses, one-leg and pair disconnect/reconnect, application backgrounding and restart, device power cycle, network handoff, token expiry, provider timeout, cancellation, barge-in, external effect after local timeout, authoritative reconciliation, latency distributions, reliability, power, thermal behavior, and soak recovery.

Speech qualification additionally binds LC3/PCM format, buffering, provider tenancy, first audio, partial and final transcript times, framework/provider finality, permission and locale behavior, interruptions, stale-generation rejection, provider retention and regional processing, raw-audio deletion, and prevention of stale transcript/model/display publication.

Raw audio, sensitive transcripts, credentials, personal device identifiers, and unrelated user content are forbidden from the evidence package.

## 6. Wave D — firmware authority and independent assurance

### 6.1 Vendor firmware authority

Only the Even G1 vendor or an explicitly delegated party can issue firmware authority. Obtain a grant defining product, hardware, firmware branch, environment, roles, and validity. Bind reproducible firmware builds, secure-boot trust chain, HSM/KMS signing custody, role separation, OTA manifest and transport, anti-rollback, failed or interrupted update behavior, recovery mode, rollback, key retirement, protocol compatibility, and witnessed physical drills.

Until this exists, the product remains a companion/mobile edge platform and must not claim ownership of vendor firmware, bootloader, secure boot, signing, OTA, recovery, or rollback.

### 6.2 Independent assurance

Independent security, privacy, legal, accessibility, and safety reviewers assess the same frozen candidate and eventual binaries. Preserve reviewer qualifications and independence, executed plans, findings, severity, owner, disposition, retest, accepted residual risk, candidate and binary digests, signatures, and final cross-discipline acceptance. High and critical findings must be resolved. Evidence issuers and source pushers may not approve their own work.

## 7. Wave E — signed binaries, pilot, rollout, rollback, and stores

Produce Android and iOS release binaries through controlled builds. Bind production signer metadata, binary digests, binary SBOMs, provenance, attestations, entitlements, permissions, release flags, malware, secret, dependency, license, and policy scans. Private signing material remains outside source and ordinary CI logs.

Run a defined pilot on the exact signed binaries and production-like infrastructure. Record population, jurisdictions, hardware, OS, firmware, duration, privacy notice, consent, support, incident path, thresholds, reliability, latency, power, thermal, crash, cancellation, reconciliation, privacy, accessibility, and support outcomes. Execute the kill switch and rollback; a design document alone is not evidence.

Define rollout cohorts, monitoring, stop thresholds, escalation, and rollback ownership. Capture actual staged decisions and telemetry. Submit the exact binaries and metadata to the relevant stores or authorized distribution channel and preserve approval identifiers. Evaluate the product release bundle with no override.

## 8. Evidence intake and validation

For each wave:

1. collect artifacts under a controlled custody root outside the checked-out repository;
2. hash exact bytes before parsing or normalization;
3. reject links, special files, path traversal, duplicate JSON keys, non-finite numbers, unknown authority fields, type confusion, stale identity, and unbounded inputs;
4. obtain detached signatures from the narrow issuing authority;
5. obtain a distinct independent acceptance signature after evidence creation;
6. validate the trust registry against its protected out-of-band digest;
7. run `tools/validate_external_evidence.py` with the exact candidate identities, `--require-complete`, and `--require-accepted`;
8. run the product release gate for release-scoped evidence;
9. preserve the immutable package URI, hashes, verification output, timestamps, registry revision, reviewer roster, and acceptance context;
10. update the corresponding GitHub issue only with redacted metadata and content-addressed references—never raw secrets or personal evidence.

## 9. Closure and reopening

A GitHub issue closes only when the corresponding gate has authentic, complete, signed, independently accepted evidence for the exact candidate and the machine verifier passes. A checklist, source test, mock, screenshot, locally generated receipt, administrator statement, model output, repository key, synthetic trace, or successful subset of CI cannot close an external row.

After all thirteen gates are accepted, regenerate a machine report showing zero `BLOCKED_ADMIN_SETTING`, `BLOCKED_EXTERNAL`, and `BLOCKED_UPSTREAM` entries, confirm the unchanged candidate and binaries, run the no-override product release gate, and obtain final release-authority acceptance. Any reopening condition in `docs/EXTERNAL_CLOSURE_PROGRAM.json` regresses the affected maturity axis until fresh evidence is issued.

## 10. Repository-side verification

```bash
python3 tools/validate_external_closure_program.py
python3 -m unittest services.qualification.test_external_closure_program
python3 tools/generate_module_docs.py --check
python3 tools/validate_module_semantics.py
```

These commands prove that source preparation and closure requirements remain complete and internally consistent. They do not prove that an external transaction has occurred.
