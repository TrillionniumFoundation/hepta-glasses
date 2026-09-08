# Source Artifact archival and long-term revalidation

Status: repository-controlled verification protocol. No archive receipt is accepted merely because this document, its schema, or its template exists.

## Problem

GitHub Actions Artifacts are useful exact-run evidence but are retention-limited. Expiry must fail closed: an expired or deleted Artifact cannot silently become permanent authority, and a copied ZIP is not trusted without a content, source-object and custodian binding.

This protocol defines a separate, content-addressed archival receipt for the exact source-evidence ZIP. The archive custodian and signing key registry are administered outside the repository. The repository supplies only a verifier, a closed schema and a non-authoritative template.

## Required objects

A revalidation packet contains three distinct files: the archived source-evidence ZIP bytes; a signed receipt conforming to `schemas/source-artifact-archive-receipt.schema.json`; and an out-of-band trust registry naming the active Ed25519 custodian key.

The receipt binds repository identity, exact source commit and tree, canonical Artifact name, independently recomputable ZIP SHA-256 and byte length, a `sha256:<digest>` archive object identifier, archive/retention timestamps, custodian and signing key identity.

The detached signature covers canonical UTF-8 JSON for every receipt field except `signature`. Members are sorted; duplicate keys, non-finite numbers, type confusion and non-canonical base64 are rejected.

## Trust boundary

The trust registry passed to the verifier must resolve outside the checked-out repository. A repository commit, pull-request attachment, issue comment, workflow output, generated fixture, or key created by the submitting actor cannot establish an independent archive authority.

The active key must be unique, Ed25519, valid at `archived_at`, and not revoked. Key rotation and revocation are performed by the external custodian. Replacing a registry in the repository to make a receipt pass is prohibited and rejected by the CLI path boundary.

## Verification

```bash
python tools/verify_source_archive_receipt.py \
  --receipt /secure-intake/receipt.json \
  --artifact /secure-intake/hepta-source-evidence-<head>.zip \
  --trust-registry /etc/hepta/archive-trust-registry.json \
  --repository-root "$PWD" \
  --expected-head <40-hex-head> \
  --expected-tree <40-hex-tree>
```

A passing result proves that the supplied ZIP bytes match the signed content address and exact source tuple. It does not replace inspection of ZIP inventory, CRC, source gate, history scan, native report, SBOM, provenance and release-bundle cross-digests.

## Creation and custody

After a canonical exact-head run succeeds, an authorized archive operator downloads the Artifact directly from GitHub, computes digest and size independently, stores the immutable object under its content address, and signs the receipt using a custodian-controlled key. The private key never enters GitHub Actions, the repository, a developer workstation, an issue, or a pull request.

At least two independent downloads should be byte-identical before signing. A receipt for a predecessor HEAD, prospective merge, regenerated ZIP, or renamed object is not transferable.

## Expiry, loss and rollback

If the Actions Artifact and external archive object are both unavailable, live revalidation is lost and the gate returns to blocked. If a digest, size, signature, key status, source object, retention term or archive object differs, reject the packet; do not repair it in place.

Extending retention or moving custody requires a newly signed receipt over the same immutable bytes. Rebuilding equivalent evidence creates a new Artifact digest and requires a new receipt and independent review.

## Claim ceiling

The schema, verifier, tests and template close only the repository-controlled protocol/tooling gap. They do not assert that an external archive exists, that a custodian accepted an object, that a key registry is independently administered, or that any production, device, provider, signing, store or release gate is satisfied.
