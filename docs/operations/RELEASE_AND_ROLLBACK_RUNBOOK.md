# Release, trusted evidence, kill-switch, and rollback runbook

## 1. Source release evidence

One unchanged exact head must complete all seven canonical jobs:

1. `repository-contracts`
2. `flutter`
3. `android-native`
4. `ios-native`
5. `native-sanitizers`
6. `secret-and-boundary-scan`
7. `source-evidence`

The final job emits `hepta-source-evidence-<exact-head-sha>` containing the source
SBOM, provenance, all-ref history scan, native sanitizer report, source release
bundle, summary, and gate result. Download the artifact independently, verify its
GitHub-reported digest, then re-read every internal digest and exact commit/tree.
A parent run, local export, skipped or empty job, manually copied SHA, or artifact
from another branch is not E4 evidence.

The source release bundle records the six prerequisite lanes consumed by the
`source-evidence` job. Completion of the seventh lane is established by the
existence and independent verification of that exact-head artifact, not by a job
claim recursively written inside its own input bundle.

## 2. Product release gate: one trusted authority path

A product release is evaluated only by the authenticated G10 external-evidence
validator. Plain JSON values such as `"verified"`, `"approved"`, `true`, a local
hash, a screenshot, or a repository-authored issuer identity are descriptive and
have no release authority.

Populate only:

- the exact source section from the verified source artifact; and
- `external_evidence.bundle`, `external_evidence.artifact_root`, and
  `external_evidence.trust_registry` as canonical repository-relative paths.

Supply the trust-registry SHA-256 through a separately administered protected
channel. Never copy the bundle's own registry digest into the environment without
independent comparison.

```bash
export HEPTA_EXTERNAL_TRUST_REGISTRY_SHA256='<protected-64-hex-pin>'
python3 tools/evaluate_release_gate.py \
  --bundle evidence/release/<release>.json \
  --mode product \
  --evidence-dir evidence/source/<exact-head> \
  --output evidence/release/<release>.gate-result.json
```

Product mode invokes `tools.external_evidence.validate_bundle` with:

- trusted current UTC time;
- the verified absolute OpenSSL runtime policy;
- the out-of-band registry pin;
- `require_complete=true` and `require_accepted=true`; and
- exact repository, commit, and tree from the source bundle.

The gate then requires all twelve authority-owned gap IDs, complete issuer-class
coverage, an accepted final review set, verified review-set integrity, and
`all_authority_owned_gaps_closed=true`. There is no override mode and no fallback
to the legacy `branch_protection`, `production`, `reviews`, `drills`, `signing`,
`pilot`, or `device_qualification` status fields.

## 3. Required authority-owned evidence

The authenticated package must cover:

- HG-0010: physical Android/iOS and G1 qualification;
- HG-0011: independent security, privacy, legal, accessibility, and safety review;
- HG-0012: signed binaries, binary provenance/attestation, pilot, rollout,
  kill-switch, rollback, and store approval;
- HG-0013: provider-side revocation and rotation of the historical credential;
- HG-0014: production model-provider tenancy and receipts;
- HG-0015: KMS/HSM identity and Android/Apple attestation;
- HG-0016: vendor firmware lifecycle authority;
- HG-0017: complete protected-main API readback;
- HG-0018: Android/iOS speech implementation and physical qualification;
- HG-0021: realtime provider and OAuth registrations;
- HG-0022: live capability adapters and authoritative reconciliation; and
- HG-0044: exact-head source artifact and eligible independent review.

Every gap uses the authority classes, exact claim partitions, signatures,
artifacts, reviewer coverage, and independence rules in
`contracts/external-evidence-envelope-v1.json`.

## 4. Kill-switch drill

Independently disable model sessions, realtime bootstrap, mutating capabilities,
a Skill, a device, and a release cohort. Confirm safe read-only status and
user-visible recovery remain available. Record the authority key ID, time, scope,
propagation latency, denial evidence, restoration authorization, exact release,
and affected tenant/cohort without storing credentials or sensitive content.

The drill is successful only when the signed authority artifact and independent
acceptance are included in the G10 package. A repository-authored `passed` field
cannot close HG-0012.

## 5. Rollback drill

1. Freeze new mutations.
2. Reconcile in-flight and indeterminate effects.
3. Roll mobile and control-plane configuration to the last approved release.
4. Verify schema, journal, lease, receipt, and downgrade compatibility.
5. Confirm revoked sessions, devices, credentials, and Skills remain revoked.
6. Re-run smoke, cancellation, duplicate-effect, and privacy checks.
7. Attach exact binary/configuration identity, timestamps, operator/reviewer key
   IDs, provider readback, and outcome to the authenticated evidence package.

## 6. Staged rollout and stop conditions

Internal operators → 5–10 users → 20–50 user pilot → broader cohort. Promotion
requires the declared observation window, statistically meaningful device-hours
and sessions, at least 99% crash-free rate, zero duplicate effects, no unresolved
high-severity finding, successful rollback rehearsal, and independent release
approval.

Stop or reopen the release when source, tree, binary, firmware, provider tenant,
OAuth registration, registry pin, signing identity, reviewer roster, pilot cohort,
or evidence digest changes. Any later push requires fresh exact-head CI, artifact
verification, and independent review.
