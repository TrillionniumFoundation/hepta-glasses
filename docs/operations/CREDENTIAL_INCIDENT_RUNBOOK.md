# Credential incident closure runbook

This runbook closes the operational evidence gap created when a credential-like value has ever existed in repository history. Deleting the value from the current tree is containment, not incident closure.

## 1. Preserve secrecy

Never paste or recover a secret into an issue, PR, log, fixture, report, command history, or evidence bundle. Identify it using provider name, credential ID or key ID, affected repository/ref, discovery time, and a SHA-256 fingerprint computed in a controlled environment.

`tools/scan_repository_history.py` emits only metadata and one-way fingerprints. CI must use a full checkout and `--fail-on-current`. Historical findings remain informational until the external provider confirms revocation or rotation.

## 2. Contain

1. Disable the affected credential at the provider before investigating usage.
2. Rotate every credential that shared the same trust boundary or deployment secret.
3. Revoke active sessions/tokens derived from the credential when the provider supports it.
4. Search all Git refs, forks under organizational control, Actions logs, caches, artifacts, releases, package registries, backups, and deployment environments.
5. Preserve provider audit records without copying request/response bodies that may contain user data.

## 3. Validate replacement

The replacement credential must be server-side, short-lived where possible, least-privileged, independently owned, and absent from mobile bundles. Exercise issue, use, rotation, revoke, lost-device, and recovery paths in a staging environment before production use.

## 4. Evidence package

Create a redacted record from `evidence/templates/credential-incident-closure.template.json`. Required evidence includes:

- exact source head and history-scan digest;
- affected provider and non-secret credential ID;
- detection, revocation, and replacement timestamps;
- provider-side revocation/rotation receipt digest;
- current-tree finding count of zero;
- scope review for forks, logs, artifacts, and deployments;
- named incident owner and an independent witness;
- final status `closed` only after the provider receipt and scope review exist.

No secret value, bearer token, signing material, raw audio, or transcript may enter the record.

## 5. Release rule

A clean current-tree scan is necessary but insufficient. The product release gate requires both a closed incident record and a valid provider revocation/rotation receipt digest. Synthetic receipts, self-attestation, or source tests cannot satisfy this gate.
