# Credential incident closure runbook

## Scope

Use this runbook when a provider credential, signing token, OAuth secret, or
other long-lived secret may have entered Git history, a build artifact, log, or
developer workstation. Repository deletion alone is not incident closure.

## Immediate containment

1. Disable or revoke the affected credential at the authoritative provider.
2. Stop deployments and jobs that still depend on it.
3. Create a replacement through the approved secret manager; never place the
   replacement in Git, CI variables printed to logs, mobile bundles, or issue
   comments.
4. Record timestamps, provider identifiers, affected environments, and owners in
   a restricted incident system. Do not copy the secret value into evidence.

## Repository remediation

1. Use the redacted history scanner to identify object IDs, paths, refs, and
   SHA-256 fingerprints without emitting match material.
2. Rewrite or retire every branch and tag that keeps the object reachable.
3. Expire obsolete artifacts and caches where the platform permits it.
4. Run the complete history scan over every fetched ref. Findings and unscanned
   bounded blobs must both be zero.

A clean scan proves only repository reachability at that point; it does not
prove provider revocation.

## Deployment rotation

1. Replace the credential through KMS/HSM or the approved secret store.
2. Restart or roll every dependent workload.
3. Verify the old credential is rejected by the provider.
4. Verify the new credential has least privilege, an owner, an expiry/rotation
   policy, and no mobile/client distribution path.

## Closure evidence

Attach only redacted evidence:

- provider revocation or disablement record;
- replacement rotation/deployment record;
- old-credential rejection test;
- clean complete-history report;
- independent security-operations approval.

The Gap Ledger entry remains `BLOCKED_EXTERNAL` until provider-side evidence is
available. No source test or administrative override may substitute for it.
