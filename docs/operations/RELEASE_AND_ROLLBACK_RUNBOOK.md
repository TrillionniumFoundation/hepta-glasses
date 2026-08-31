# Release, kill-switch, and rollback runbook

## 1. Source release evidence

One unchanged exact head must complete all seven required jobs:

1. `repository-contracts`
2. `flutter`
3. `android-native`
4. `ios-native`
5. `native-sanitizers`
6. `secret-and-boundary-scan`
7. `source-evidence`

The final job emits `hepta-source-evidence-<exact-head-sha>` containing:

- `source-sbom.spdx.json`
- `source-provenance.json`
- `source-history-scan.json`
- `source-native-sanitizer.json`
- `source-release-bundle.json`
- `source-evidence-summary.json`
- `source-gate-result.json`

The artifact must bind the exact commit and tree, report zero unacknowledged history findings and zero unscanned blobs, use audit contract `file-lock-checkpoint-v2`, and pass content re-verification. A parent run, local export, skipped job, manually written SHA, or artifact from another branch is not E4 evidence.

## 2. Product release gate

Populate `evidence/templates/product-release-bundle.template.json`, then run:

```bash
python3 tools/evaluate_release_gate.py \
  --bundle evidence/release/<release>.json \
  --mode product
```

There is no override mode. Source evidence cannot replace physical devices, deployed identity/attestation, provider receipts, independent assurance, signing, pilot, or store approval.

## 3. Release inputs

- protected `main` verified from GitHub;
- independent latest-head approval and resolved conversations;
- Android and iOS physical qualification reports;
- deployed KMS/HSM and platform attestation evidence;
- production capability and realtime receipts;
- vendor firmware/OTA authority or an explicit product boundary excluding it;
- security, privacy, legal, and accessibility approvals;
- provider credential rotation/revocation closure;
- Android/iOS signing digests, binary provenance, and attestation;
- pilot cohort of at least 5 with crash-free rate at least 99%;
- zero duplicate effects;
- passing kill-switch and rollback drills.

## 4. Kill-switch drill

Independently disable model sessions, realtime bootstrap, mutating capabilities, a Skill, a device, and a release cohort. Confirm safe read-only status and user-visible recovery remain available. Record issuer, time, scope, propagation latency, denial evidence, and restoration authorization without storing credentials or sensitive content.

## 5. Rollback drill

1. Freeze new mutations.
2. Reconcile in-flight and indeterminate effects.
3. Roll mobile/control-plane configuration to the last approved release.
4. Verify schema, journal, and downgrade compatibility.
5. Confirm revoked sessions, devices, and Skills remain revoked.
6. Re-run smoke, cancellation, and duplicate-effect checks.
7. Attach exact build identity, timestamps, operator/reviewer identities, and outcome.

## 6. Staged rollout

Internal operators → 5–10 users → 20–50 user pilot → broader cohort. Promotion requires the declared SLO window, at least 99% crash-free rate, zero duplicate effects, no unresolved high-severity finding, successful rollback rehearsal, and independent release approval.
