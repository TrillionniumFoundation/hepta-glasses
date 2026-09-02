# Authenticated authority-owned evidence staging

This directory is a custody boundary for evidence that may close G9 authority-owned gaps. Files stored here are not trusted merely because they are committed, uploaded, hashed, or reviewed in a pull request.

## Required package layout

```text
evidence/external/
  <candidate-commit>/
    bundle.json
    trust-registry.json
    keys/
      <pinned-ed25519-public-key>.pem
    artifacts/
      <gap-id>/...
      reviews/...
      signatures/...
    validation-result.json
```

`bundle.json` uses `hepta-external-evidence-envelope-v1`, schema version 2. Every submission and every acceptance decision carries an Ed25519 signature over a canonical exact-subject statement. Artifact URIs use `artifact://`; public-key URIs use `key://` and resolve relative to `trust-registry.json`.

## Non-self-issuable trust

The trust registry binds each key ID to an identity, organization, authority class, allowed gaps, usage, validity interval, and revocation state. A copy of the registry may be kept with the custody package, but its SHA-256 is **not trusted from the bundle or repository**. The expected registry digest must be supplied out of band by a separately administered release or assurance controller.

A repository writer cannot close a gap by inventing a key, replacing a public key, declaring themselves independent, or recomputing local hashes. Validation rejects unknown, expired, revoked, cross-gap, issuer-alias, and cryptographically invalid signatures.

## Privacy and secret boundary

Never commit or upload raw provider credentials, OAuth refresh tokens, KMS/HSM private material, application signing keys, recovery secrets, raw microphone audio, sensitive transcripts, unredacted customer data, precise location histories, or live exploitation secrets. Only public verification keys belong in the trust package. Private signing keys remain with the issuing authority.

Use opaque KIDs, tenant IDs, receipt IDs, revocation timestamps, hashes, redacted logs, signed summaries, and independently verifiable attestations.

## Validation

```bash
python3 tools/validate_external_evidence.py \
  --bundle evidence/external/<commit>/bundle.json \
  --artifact-root evidence/external/<commit>/artifacts \
  --trust-registry evidence/external/<commit>/trust-registry.json \
  --expected-trust-registry-sha256 "$HEPTA_EXTERNAL_TRUST_REGISTRY_SHA256" \
  --expected-commit <40-hex-source-commit> \
  --expected-tree <40-hex-source-tree> \
  --require-complete \
  --require-accepted \
  --output evidence/external/<commit>/validation-result.json
```

For committed accepted packages, CI requires `HEPTA_EXTERNAL_TRUST_REGISTRY_SHA256` from a protected, out-of-band configuration source. A digest written into the same pull request is not a trust anchor.

## Signature subjects

An issuer signs the candidate identity, trust-registry binding, gap, evidence level, identity, authority class, environment, subjects, claims, artifact digests, result, limitations, and notes. A reviewer signs the same candidate and registry binding, the complete evidence-set digest, reviewed gaps, decision, and the digest of the review artifact.

Optional per-artifact signatures are verified over the exact artifact bytes under the issuer key. They supplement, but do not replace, the required signed submission statement.

## Ledger update rule

The Gap Ledger changes only in a separate reviewed commit after the complete package passes with an externally pinned registry, every gap has signed approval coverage, independence-required gaps have distinct independent approval, the candidate remains unchanged, and no key or artifact is expired or revoked. Any later source, binary, firmware, provider, OAuth registration, repository-setting, trust-registry, key, or review-state change reopens the affected row.
