# G9 terminal authority-owned gap closure

Status: canonical execution package layered on plan revision `2026-09-01-g8` without changing the G8 source candidate.

## 1. Objective

G8 closed the repository-actionable implementation surface and established an exact-head E4 source candidate. G9 exists to close the remaining authority-owned rows using evidence that only physical devices, deployed providers, repository administrators, vendors, independent reviewers, signing authorities, pilot operators, and stores can issue.

G9 must not rename a template, synthetic trace, local test, source artifact, screenshot, or self-review into E5, E6, or E7 evidence. A blocked row changes state only after its authoritative evidence bundle passes deterministic validation and independent review.

## 2. Frozen source authority

The G8 pull request remains the source authority. Its live head and tree, rather than this document, determine the candidate identity. Any source push invalidates prior exact-head CI and any approval bound to the previous head.

This G9 branch is an operations and evidence-contract branch. It must not be merged into the frozen candidate merely to create the appearance of closure. A later candidate may adopt these files and regenerate E4.

## 3. Remaining rows and issuing authorities

| Gap | Required authority | Minimum evidence level |
|---|---|---|
| HG-0010 | Android/iOS device lab and Even G1 owner | E5 |
| HG-0011 | Independent security, privacy, legal, accessibility, and safety reviewers | E6 |
| HG-0012 | Android/iOS signing, pilot, rollout, rollback, and store authorities | E7 |
| HG-0013 | Historical credential provider and incident owner | E5/E6 |
| HG-0014 | Production model-provider tenant owner and cloud security | E5 |
| HG-0015 | KMS/HSM and Apple/Android attestation owners | E5/E6 |
| HG-0016 | Firmware vendor | E6/upstream |
| HG-0017 | Repository administrator plus fresh GitHub API observation | administrative |
| HG-0018 | Android ASR provider and iOS physical speech lab | E5 |
| HG-0021 | Production realtime/OAuth provider owners | E5 |
| HG-0022 | Production capability-provider owners | E5 |
| HG-0044 | Eligible non-pusher reviewer on the unchanged exact head | E6/governance |

## 4. Closure protocol

Every submitted bundle must use `contracts/external-evidence-envelope-v1.json` and pass `tools/validate_external_evidence.py`.

The validator enforces:

1. exact repository, source commit, source tree, contract revision, and collection-time binding;
2. a complete SHA-256 digest for every referenced artifact;
3. an issuer whose authority class is permitted for the claimed gap;
4. explicit environment, device/provider/firmware versions, result, limitations, and expiry where applicable;
5. no raw credentials, signing keys, raw audio, or sensitive transcript content;
6. no self-review for independent assurance or latest-head approval;
7. no synthetic or digital-twin evidence for physical-device claims;
8. all gap-specific required claims before an item becomes `eligible_for_review`;
9. an independent acceptance record before a ledger row becomes `CLOSED_VERIFIED`;
10. fail-closed behavior on unknown fields, unknown gaps, digest mismatch, stale candidate identity, missing artifacts, or ambiguous results.

`eligible_for_review` is not closure. The Gap Ledger is changed only in a separate reviewed commit that cites the accepted evidence and records the reviewer.

## 5. Execution waves

### Wave A — governance and independent source approval

- Apply `contracts/main-branch-protection-v1.json` to `main`.
- Read the settings back through the GitHub API and attach the redacted observation.
- Require all seven checks, strict mode, administrator enforcement, CODEOWNER review, last-push approval, stale-review dismissal, conversation resolution, linear history, and disabled force-push/deletion.
- Obtain an eligible non-pusher approval on the unchanged G8 head after the complete matrix succeeds.

These two actions close HG-0017 and HG-0044 without changing source.

### Wave B — incident, identity, and provider tenancy

- Revoke and rotate the historically exposed credential provider-side.
- Deploy KMS/HSM identities and platform attestation.
- Qualify production model and realtime/OAuth tenants.
- Qualify every enabled capability adapter with authoritative receipts and reconciliation.

This wave targets HG-0013, HG-0014, HG-0015, HG-0021, and HG-0022.

### Wave C — physical device and speech

- Run the declared Android and iOS G1 matrix on signed applications and declared firmware.
- Collect protocol, loss/reconnect, latency, power, thermal, cancellation, barge-in, and soak traces.
- Deploy Android PCM-to-ASR and run the iOS locale/device finality matrix.

This wave targets HG-0010 and HG-0018.

### Wave D — independent assurance and release

- Freeze the candidate after all Wave B/C evidence passes.
- Complete independent security, privacy, legal, accessibility, safety, and vendor review.
- Produce signed binaries and binary SBOM/provenance/attestation.
- Complete pilot, kill-switch, rollback, staged rollout, and store approval.

This wave targets HG-0011, HG-0012, and HG-0016.

## 6. Parallel ownership

Each gap has one accountable owner and may have multiple evidence producers. Producers work in parallel, but only the closure controller may assemble a candidate bundle. Independent reviewers must not be the implementing or evidence-producing identity. Repository administrators may apply settings but may not attest settings that were not read back from the API.

## 7. Stop conditions

The closure campaign stops and reopens the affected row when:

- the source head or tree changes;
- a production binary digest changes;
- a provider tenant, key, OAuth registration, firmware, device, or store build differs from the declared subject;
- evidence expires or is revoked;
- an independent reviewer reports an unresolved finding;
- a required GitHub protection field cannot be observed;
- a physical test uses a simulator, digital twin, or undeclared firmware;
- an artifact digest or signature cannot be verified.

## 8. Definition of all gaps closed

All gaps are closed only when:

- every repository-actionable row is `CLOSED_SOURCE` or `CLOSED_VERIFIED`;
- each of the 12 authority-owned rows has a complete accepted envelope;
- the live G8/G9 candidate identity has not changed after the last bound approval;
- the product release gate passes with no override;
- a fresh machine report returns zero `OPEN`, `BLOCKED_EXTERNAL`, `BLOCKED_ADMIN_SETTING`, or `BLOCKED_UPSTREAM` rows.

Until those facts exist, the truthful state is source-complete but product-blocked.