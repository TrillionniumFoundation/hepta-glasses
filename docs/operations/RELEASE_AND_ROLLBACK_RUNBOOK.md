# Release, staged rollout, and rollback runbook

## Source candidate

A source candidate is eligible for independent review only when the exact PR head passes all canonical checks: repository contracts, Flutter, Android native/release configuration, iOS native/release configuration, native sanitizers/fuzzing, secret/boundary/full-history scanning, and source evidence. The artifact must bind the same commit, tree, plan revision, multi-ecosystem source inventory, vendored component digest, and credential-history digest.

Do not reuse a pre-merge artifact for the merge commit. After an independent approval and protected merge, rerun the checks on `main` and generate a new exact-head artifact.

## Product release inputs

The product bundle must include:

- verified `main` protection and required checks;
- passing physical Android and iOS + Even G1 qualification reports;
- production KMS/HSM, attestation, rotation, revoke, and recovery evidence;
- production realtime/OAuth/provider receipts and timeout reconciliation;
- closed credential incident record with provider revocation/rotation receipt;
- independent security, privacy, legal, accessibility, safety, and supply-chain decisions;
- signed Android and iOS artifact digests;
- binary SBOM digest and signed artifact-attestation/provenance digest;
- pilot cohort, crash-free rate, duplicate-effect count, privacy metrics, and support readiness;
- witnessed kill-switch and rollback drill records.

The product release gate has no override path. Source artifacts, synthetic traces, self-review, unsigned binaries, or source SBOMs are forbidden substitutes.

## Staged rollout

1. Publish signed artifacts to an internal cohort.
2. Confirm identity/revocation, device compatibility, BLE reconnect, cancellation, timeout reconciliation, telemetry minimization, and support paths.
3. Expand only when the current stage satisfies the signed SLO and no un-reconciled mutation remains.
4. Stop rollout on any duplicate side effect, unexplained audit-chain failure, credential exposure, attestation bypass, privacy breach, or inability to revoke.
5. Record every stage decision with artifact digest, cohort, start/end time, owner, independent approver, metrics, and rollback target.

## Kill switch

The control plane must be able to disable provider sessions, capability mutations, affected device generations, Skill packages, and release cohorts independently. The mobile runtime must fail closed when a required revocation state cannot be established. A drill is passing only when independently witnessed and bound to production-equivalent identities and signed artifacts.

## Rollback

Rollback must restore the previous signed artifact and compatible server contract without replaying uncertain effects or accepting stale leases/tokens/generations. Reconcile every prepared/indeterminate mutation before resuming service. Verify audit continuity, device reconnect, token revocation, data retention/deletion, and support communication.

A rollback is not complete until monitoring is stable, all affected identities are accounted for, and an independent owner approves the evidence package.
