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
      successors/...
    validation-result.json
```

`bundle.json` uses `hepta-external-evidence-envelope-v1`, schema version 2. Every submission and every acceptance decision carries an Ed25519 signature over a canonical exact-subject statement. Artifact URIs use `artifact://`; public-key URIs use `key://` and resolve relative to `trust-registry.json`.

## Non-self-issuable trust

The trust registry binds each key ID to an identity, organization, authority class, allowed gaps, usage, validity interval, and revocation state. A copy of the registry may be kept with the custody package, but its SHA-256 is **not trusted from the bundle or repository**. The expected registry digest must be supplied out of band by a separately administered release or assurance controller.

A repository writer cannot close a gap by inventing a key, replacing a public key, declaring themselves independent, or recomputing local hashes. Validation rejects unknown, expired, revoked, cross-gap, issuer-alias, and cryptographically invalid signatures.

## Filesystem custody and stable byte snapshots

A valid URI is not a stable byte identity by itself. Paths must use one canonical POSIX relative spelling: absolute paths, empty components, repeated or trailing separators, `.` and `..` are rejected.

During one validation transaction, every existing `artifact://` and `key://` input is pinned to the first stable bytes observed for its normalized lexical path. The stable read captures the device, inode, and object type of every ancestor directory plus the complete identity of the final regular file. A second no-follow descriptor traversal must match those captured identities before bytes are accepted. Symbolic-link redirection, ordinary-object replacement after capture, same-name replacement, non-regular objects, oversized files, short reads, scope escapes, and metadata changes fail closed or cannot alter the pinned transaction bytes.

The transaction has both per-file limits and a 512 MiB aggregate snapshot ceiling. Very large raw measurement collections should be stored separately and referenced by authenticated content manifests rather than forcing the validator to retain every raw byte.

PEM hashing, Ed25519 key-type verification, normalized DER-SPKI uniqueness, and signature verification use the same pinned public-key bytes. OpenSSL receives a private temporary copy of the snapshot and never reopens the authority-controlled key pathname for a later cryptographic phase.

## Signing custody

Private keys never enter repository or evidence custody. The signing helper reads the selected private key once through a bounded stable descriptor, then performs key-type inspection and signing on the same private temporary snapshot. Replacing the original key pathname after capture cannot change the signing key.

Detached signatures are always new files. The helper walks the custody root with directory descriptors, rejects symbolic-link directory components, creates missing directories with mode `0700`, and creates the final signature with no-follow and exclusive-create semantics at mode `0600`. Existing regular files, dangling links, output links, overwrite attempts, partial writes, and unsupported secure directory APIs fail closed.

The helper supports two bundle-output modes:

- default compatibility mode verifies the exact unchanged parent chain, input object, and input bytes, stages a complete mode-0600 successor, and atomically replaces that exact input name;
- `--output-bundle-uri artifact://successors/<name>.json` creates a new exclusive successor and leaves the input bundle byte-for-byte unchanged. This mode is preferred for independently reviewed custody.

If a signature is created but a later bundle commit fails, no bundle success is reported. An unreferenced signature may remain and must not be represented as accepted evidence.

The normative decisions and negative-test requirements are recorded in `docs/adr/ADR-0006-external-evidence-filesystem-custody.md` and `docs/adr/ADR-0007-evidence-object-identity-and-bounded-custody.md`. These controls protect local evidence I/O; they do not make repository custody an external trust anchor.

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
