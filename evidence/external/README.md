# Authenticated authority-owned evidence staging

This directory is a custody boundary for evidence that may close authority-owned gaps. Files stored here are not trusted merely because they are committed, uploaded, hashed, or reviewed in a pull request.

## Active protocol

- Envelope: `hepta-external-evidence-envelope-v1`, schema version 2
- Contract revision: `2026-09-02-g10-quorum-1`
- Complete-closure policy: `hepta-external-complete-closure-v1`
- Predecessor: `2026-09-02-g9-authenticated-1`
- Signature profile: Ed25519 over canonical UTF-8 JSON

A statement signed under the predecessor revision does not satisfy the G10 policy. Contract revision is part of every issuer and reviewer signature preimage, while policy ID and revision are also part of the final review-set and acceptance-context digests.

## Required package layout

```text
evidence/external/
  <candidate-commit>/
    bundle.json
    trust-registry.json
    keys/
      <pinned-ed25519-public-key>.pem
    artifacts/
      <gap-id>/<authority-class>/...
      reviews/...
      signatures/...
      successors/...
    validation-result.json
```

`bundle.json` is an initial, non-authoritative predecessor. Every authority-bearing signing operation writes a fresh immutable successor under `artifact://successors/...`; in-place mutation is rejected.

Artifact URIs use `artifact://`. Public-key URIs use `key://` and resolve relative to `trust-registry.json`.

## Non-self-issuable trust

The trust registry binds each key ID to an identity, organization, authority class, allowed gaps, usage, validity interval, and revocation state. A copy may accompany the custody package, but its digest is **not trusted from the bundle or repository**. The expected SHA-256 must arrive through a separately administered, protected out-of-band channel.

Validation rejects unknown, expired, revoked, cross-gap, wrong-usage, key-alias, normalized-SPKI-reuse, issuer/reviewer-alias, and cryptographically invalid signatures. Only Ed25519 public keys with the expected SubjectPublicKeyInfo form are accepted.

Private keys never belong in repository, CI artifact, log, issue, pull request, or evidence custody. The signing helper rejects a private key located inside the declared custody root.

## Filesystem custody and stable byte snapshots

A URI is not a stable byte identity by itself. Paths use one canonical POSIX relative spelling; absolute paths, empty components, repeated or trailing separators, `.` and `..` are rejected.

During one validation transaction, every existing `artifact://` and `key://` input is pinned to the first stable bytes observed for its normalized lexical path. Reads capture the device, inode, and type of every ancestor directory plus the final regular file. A second no-follow descriptor traversal must match those captured identities before bytes are accepted.

Symbolic-link redirection, ordinary-directory or file replacement, same-name substitution, non-regular objects, oversized files, short reads, scope escapes, and metadata changes fail closed or cannot alter the pinned view. The transaction enforces per-file bounds and a 512 MiB aggregate snapshot ceiling.

PEM hashing, key-type inspection, normalized DER-SPKI uniqueness, and signature verification consume the same pinned public-key bytes. OpenSSL receives private temporary copies and does not reopen authority-controlled paths during later cryptographic phases.

## Signing custody

The input bundle, artifacts, signatures, and successors share one declared custody root. The signer:

1. snapshots the selected private key once outside custody;
2. uses that snapshot for both Ed25519 type inspection and signing;
3. validates canonical, distinct output URIs;
4. creates detached signatures and bundle successors exclusively as mode-0600 regular files through no-follow directory descriptors;
5. leaves every predecessor bundle byte-for-byte unchanged;
6. reopens and byte-compares visible outputs before reporting success; and
7. never treats an unreferenced signature as authority.

Example:

```bash
python3 tools/sign_external_evidence.py submission \
  --bundle <custody-root>/bundle.json \
  --custody-root <custody-root> \
  --output-bundle-uri artifact://successors/submission-001.json \
  --index 0 \
  --private-key <authority-private-key-outside-custody.pem> \
  --signature-uri artifact://signatures/submission-001.sig
```

Each later command uses the verified successor as input and allocates fresh output names. Existing output names are never overwritten. If successor publication fails after signature creation, the command fails; the unreferenced signature remains non-authoritative.

The normative filesystem decisions are `docs/adr/ADR-0006-external-evidence-filesystem-custody.md` and `docs/adr/ADR-0007-evidence-object-identity-and-bounded-custody.md`.

## Complete issuer quorum

A complete package requires a valid submission from **every authority class** listed for each gap in `contracts/external-evidence-envelope-v1.json`. Multiple submissions per gap are expected.

Within one gap, every authority seat uses:

- a distinct trust-registry key ID; and
- a distinct `(identity, organization)` pair.

A broadly scoped key cannot fill two seats by changing the class label.

## Exact authority-scoped claims

`required_claims_by_authority_class` is a disjoint and exhaustive partition of each gap's `required_claims`. Each issuer signs **only** the claims assigned to its authority class:

- missing assigned claims fail;
- claims assigned to another class fail;
- false or non-boolean required claims fail; and
- the full gap claim boundary exists only after every class-specific signed submission is present.

Examples:

- the repository administrator signs the configured protection controls, while the GitHub API observer signs the fresh readback;
- the credential provider signs revocation facts, while the incident owner signs replacement scope and incident closure;
- signing, pilot, and store authorities sign their separate release claims.

The validator reports `issuer_claim_scopes`, `issuer_authority_coverage`, and `missing_issuer_authority_classes`. Any missing class prevents eligibility and closure.

## Final reviewer roster and acceptance manifest

Freeze the complete ordered reviewer roster and acceptance context before final reviewer signatures. Compute:

```python
from tools.external_evidence import (
    acceptance_context_digest,
    review_set_digest,
)

roster_digest = review_set_digest(bundle["acceptance"]["reviewers"])
context_digest = acceptance_context_digest(
    bundle["acceptance"],
    roster_digest=roster_digest,
)
```

Every final review artifact is UTF-8 JSON containing:

```json
{
  "closure_manifest": {
    "schema_version": 1,
    "policy_id": "hepta-external-complete-closure-v1",
    "policy_revision": "2026-09-02-g10-quorum-1",
    "review_set_digest": "<roster_digest>",
    "acceptance_context_digest": "<context_digest>"
  }
}
```

The review artifact may also contain a summary and content-addressed references to a separate report. Set `review_uri` and `review_sha256` to this final JSON artifact, then issue the reviewer signature.

All final reviewers bind the same roster and context. Adding, removing, replacing, or reordering a reviewer—or changing state, `reviewed_at`, `decision_reference`, or limitations—invalidates every surviving manifest. Recomputing the unsigned bundle digest cannot repair the mismatch.

The manifest protects the final roster that its members co-signed. It cannot discover a review never admitted to the roster; reviewer selection and any external transparency register remain governance responsibilities.

The normative complete-closure decision is `docs/adr/ADR-0008-authority-quorum-and-review-set-integrity.md`.

## Privacy and secret boundary

Never commit or upload raw provider credentials, OAuth refresh tokens, KMS/HSM private material, application signing keys, recovery secrets, raw microphone audio, sensitive transcripts, unredacted customer data, precise location histories, or live exploit details.

Use opaque KIDs, tenant IDs, receipt IDs, revocation timestamps, hashes, redacted logs, signed summaries, and independently verifiable attestations.

## Validation

```bash
python3 tools/validate_external_evidence.py \
  --bundle evidence/external/<commit>/successors/finalized.json \
  --artifact-root evidence/external/<commit>/artifacts \
  --trust-registry evidence/external/<commit>/trust-registry.json \
  --expected-trust-registry-sha256 "$HEPTA_EXTERNAL_TRUST_REGISTRY_SHA256" \
  --expected-commit <40-hex-source-commit> \
  --expected-tree <40-hex-source-tree> \
  --require-complete \
  --require-accepted \
  --output evidence/external/<commit>/validation-result.json
```

For committed accepted packages, CI requires the protected out-of-band registry pin. Repository qualification recursively inspects every bounded regular file under `evidence/external/` and identifies accepted envelopes by canonical content—not filename, extension, or directory depth. An opaque immutable successor cannot avoid validation by being renamed or nested.

## Ledger update rule

A Gap Ledger row changes to `CLOSED_VERIFIED` only in a separate reviewed commit after:

- every required issuer class has participated through a distinct key and identity/organization pair;
- every class signs exactly its assigned claims and evidence;
- the complete package passes under the out-of-band registry pin;
- every gap has valid approving reviewer coverage;
- every final review artifact binds the same G10 policy, roster, and acceptance context;
- independence-required gaps have distinct independent approval;
- source, binary, firmware, provider, OAuth, repository-setting, registry, key, and review identities remain unchanged; and
- no artifact or key is expired or revoked.

Any material identity or authority change reopens the affected row.
