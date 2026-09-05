# G9 authenticated terminal authority-owned gap closure

Status: canonical execution package layered on plan revision `2026-09-01-g8` without changing the frozen G8 source candidate.

G9 contract revision: `2026-09-02-g9-authenticated-1`.

## 1. Objective

G8 closes the repository-actionable implementation surface and establishes an exact-head E4 source candidate. G9 closes the remaining authority-owned rows only with evidence issued by physical-device labs, deployed providers, repository administrators, vendors, independent reviewers, signing authorities, pilot operators, and stores.

A template, simulator result, local JSON file, source artifact, screenshot, repository-written identity, or self-review cannot become E5, E6, or E7 evidence by renaming or hashing it. A blocked row changes state only after its exact-subject evidence and acceptance decisions are cryptographically authenticated, deterministically validated, independently reviewed, and bound to the unchanged candidate.

## 2. Frozen source authority

The G8 pull request remains the source authority until it is intentionally superseded. Its live head and tree, rather than prose, determine the candidate identity. Any source or base movement invalidates prior exact-head CI, source artifacts, evidence signatures, and approval bound to the previous object.

This G9 branch is an operations and evidence-authentication branch. It must not be merged into the frozen G8 candidate merely to create the appearance of closure. A later candidate may adopt G9 and must then regenerate all seven E4 jobs and its content-addressed source artifact.

## 3. Threat model for evidence

The evidence system assumes a repository writer may create or edit JSON, artifacts, hashes, public-key files, review fields, and acceptance state. Therefore none of those values may authenticate themselves.

G9 uses the following trust boundary:

1. every issuer and reviewer owns an Ed25519 private key outside the repository;
2. a separately administered trust registry binds the public key digest to identity, organization, authority class, permitted gaps, usage, validity interval, and revocation state;
3. the expected trust-registry SHA-256 is supplied out of band by a protected release or assurance controller;
4. the digest declared inside the bundle must match that external pin but is never accepted as its own anchor;
5. every evidence submission signs a canonical statement containing the exact candidate, registry binding, claims, subjects, limitations, and artifact digests;
6. every reviewer signs a canonical decision containing the exact candidate, registry binding, complete evidence-set digest, reviewed gaps, decision, and review-artifact digest;
7. issuer/reviewer key aliases are rejected; independence-required rows require a distinct independent key and organization;
8. expired, revoked, unknown, cross-gap, substituted-key, malformed, and cryptographically invalid signatures fail closed.

Optional per-artifact signatures are verified over the exact artifact bytes. They supplement, but do not replace, the required signed submission statement.

## 4. Remaining rows and issuing authorities

| Gap | Required evidence issuer | Required acceptance authority | Minimum level |
|---|---|---|---|
| HG-0010 | Android/iOS physical-device lab and G1 owner | release acceptance authority | E5 |
| HG-0011 | independent security, privacy, legal, accessibility, and safety reviewers | independent assurance | E6 |
| HG-0012 | Android/iOS signing, pilot, rollout, rollback, and store authorities | release acceptance authority | E7 |
| HG-0013 | historical credential provider and incident owner | release acceptance authority | E5/E6 |
| HG-0014 | production model-provider tenant owner and cloud security | release acceptance authority | E5 |
| HG-0015 | KMS/HSM and Apple/Android attestation owners | release acceptance authority | E5/E6 |
| HG-0016 | firmware vendor | release acceptance authority | E6/upstream |
| HG-0017 | repository administrator or GitHub API observer | repository governance reviewer | ADMIN |
| HG-0018 | Android ASR owner and iOS physical speech lab | release acceptance authority | E5 |
| HG-0021 | production realtime and OAuth owners | release acceptance authority | E5 |
| HG-0022 | production capability-provider owners | release acceptance authority | E5 |
| HG-0044 | exact-head source reviewer | independent code reviewer | E6/governance |

## 5. Authenticated closure protocol

Every package uses:

- `contracts/external-evidence-envelope-v1.json`;
- `schemas/external-evidence-envelope.schema.json`;
- `schemas/external-authority-trust-registry.schema.json`;
- `tools/validate_external_evidence.py`.

The validator enforces:

1. exact repository, source commit, source tree, contracts revision, release identity, and collection time;
2. an externally supplied trust-registry digest that matches the package copy and every signed statement;
3. actual SHA-256 verification of registry public keys, evidence artifacts, review artifacts, and signatures;
4. Ed25519 verification through OpenSSL, with no network lookup and no private keys in the package;
5. issuer identity, organization, authority class, key usage, allowed gap, validity interval, and revocation state;
6. required claims, environment, subjects, result, limitations, artifact issue time, expiry, and secret-content boundaries;
7. no synthetic or digital-twin evidence for physical-device rows;
8. no issuer key or identity reused as an acceptance reviewer;
9. approving reviewer coverage for every submitted gap;
10. distinct independent approving coverage for HG-0011 and HG-0044;
11. a canonical bundle digest after all signed decisions are attached;
12. fail-closed behavior on unknown fields, unknown gaps, path escape, digest drift, candidate drift, registry substitution, missing external pin, malformed signatures, or ambiguous outcomes.

`eligible_for_review` is not closure. The Gap Ledger changes only in a separate reviewed commit that cites an accepted package and records the reviewer and validation result.

## 6. Trust-registry administration

The trust registry is not owned by the feature branch that submits evidence. A release-security or assurance controller maintains its authoritative digest in protected configuration outside the pull request.

Key registration requires:

- proof of private-key possession;
- verified legal or organizational identity;
- explicit authority classes and allowed gaps;
- the narrowest required usage;
- bounded validity;
- documented rotation and revocation contacts;
- a public-key SHA-256 calculated before registration.

A registry copy may accompany an evidence package for reproducibility, but changing that copy requires a new external pin and invalidates all statements signed against the prior registry digest. Private keys never enter source control, Actions artifacts, ordinary logs, or evidence packages.

## 7. Execution waves

### Wave A — governance and independent source approval

- Apply `contracts/main-branch-protection-v1.json` to `main`.
- Read all settings back through the GitHub API and export the redacted observation.
- Require all seven checks, strict mode, administrator enforcement, CODEOWNER review, last-push approval, stale-review dismissal, conversation resolution, linear history, and disabled force-push/deletion.
- Obtain an eligible non-pusher approval on the unchanged G8 head after the complete matrix succeeds.
- Sign the HG-0017 and HG-0044 submissions and their acceptance decisions with pinned keys.

These actions close HG-0017 and HG-0044 without changing G8 source.

### Wave B — incident, identity, and provider tenancy

- Revoke and rotate the historically exposed credential provider-side.
- Deploy KMS/HSM identities and platform attestation.
- Qualify production model and realtime/OAuth tenants.
- Qualify every enabled capability adapter with authoritative receipts and reconciliation.
- Export redacted provider records, sign each exact-subject submission, and obtain release acceptance.

This wave targets HG-0013, HG-0014, HG-0015, HG-0021, and HG-0022.

### Wave C — physical device and speech

- Run the declared Android and iOS G1 matrix on signed applications and declared firmware.
- Collect protocol, loss/reconnect, latency, power, thermal, cancellation, barge-in, and soak traces.
- Deploy Android PCM-to-ASR and run Android/iOS locale, device, finality, latency, cancellation, and privacy matrices.
- Preserve lab custody and sign each report with a pinned physical-lab key.

This wave targets HG-0010 and HG-0018.

### Wave D — independent assurance and release

- Freeze source, binary, provider, registry, and firmware identities after Wave B/C evidence passes.
- Complete independent security, privacy, legal, accessibility, safety, and vendor review.
- Produce signed binaries and binary SBOM, provenance, and attestation.
- Complete pilot, kill-switch, rollback, staged rollout, and store approval.
- Obtain signed independent and release-acceptance decisions over the complete evidence set.

This wave targets HG-0011, HG-0012, and HG-0016.

## 8. Parallel ownership

Each gap has one accountable owner and may have multiple evidence producers. Producers work in parallel, but only the closure controller assembles a candidate package. Independent reviewers cannot be an issuer, operator, implementing identity, key alias, or same-organization evidence producer for the gap they independently approve.

Repository administrators may apply settings but may not attest settings that were not read back from the API. A release controller may coordinate acceptance but cannot replace an issuer or independent specialist.

## 9. Stop and reopen conditions

The closure campaign stops or reopens the affected row when:

- source head, source tree, base, production binary, or bundle digest changes;
- trust-registry digest changes;
- an issuer or reviewer key expires or is revoked;
- provider tenant, KMS key, OAuth registration, firmware, device, store build, or signing identity differs from the signed subject;
- an artifact digest or Ed25519 signature fails;
- a required GitHub protection field cannot be observed;
- a physical test uses a simulator, digital twin, undeclared firmware, or unsigned/unknown application;
- an independent reviewer reports an unresolved finding;
- evidence expires or its issuing authority withdraws it.

## 10. Definition of all gaps closed

All gaps are closed only when:

- every repository-actionable row is `CLOSED_SOURCE` or `CLOSED_VERIFIED`;
- all 12 authority-owned rows have complete, accepted, cryptographically authenticated packages;
- the externally pinned registry is current and no relevant key is revoked or expired;
- every submitted gap has signed approving reviewer coverage;
- HG-0011 and HG-0044 have distinct independent signed approval;
- the live candidate identity has not changed after the last bound approval;
- the product release gate passes with no override;
- a fresh machine report returns zero `OPEN`, `BLOCKED_EXTERNAL`, `BLOCKED_ADMIN_SETTING`, or `BLOCKED_UPSTREAM` rows.

Until those real-world facts exist, the truthful state remains **source-complete but product-blocked**.
