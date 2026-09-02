# ADR-0008: Require complete issuer quorum and bind the final review set

- Status: accepted for G10 source
- Date: 2026-09-02
- Extends: `ADR-0004-external-evidence-authentication.md`
- Extends: `ADR-0007-evidence-object-identity-and-bounded-custody.md`
- Plan revision: `2026-09-02-g10-quorum-1`

## Context

G9 authenticates each evidence submission and each reviewer decision under an
externally pinned Ed25519 trust registry. It binds the candidate, claims,
artifact digests, limitations, decision, reviewed gaps, and evidence-set digest.
Those controls prevent a repository writer from inventing an authority identity
or altering a signed statement.

Two complete-closure weaknesses remained.

First, the canonical contract names more than one issuer authority class for
several gaps. Examples include physical-device lab plus mobile release owner,
credential provider plus incident owner, release signing plus pilot plus store
authority, and repository administrator plus independent API observer. The G9
bundle validator accepted only one submission per gap and therefore treated any
one allowed class as sufficient. A single broadly authorized key could assert
all required claims without the other named authority seats participating.

Second, each reviewer signature authenticated its own reviewer object and the
complete evidence-set digest, but not the final reviewer roster or the
acceptance-level state. A curator could remove a signed dissenting or limiting
review, recompute the unsigned bundle digest, and leave the remaining reviewer
signatures valid. The validator would see only the surviving reviews.

## Decision

### Complete issuer quorum

A bundle may contain multiple independently signed submissions for the same
gap. For complete closure, every authority class listed in
`contracts/external-evidence-envelope-v1.json` for that gap must have at least
one cryptographically valid submission.

Within one gap:

1. each authority seat uses a distinct trust-registry key ID;
2. each authority seat uses a distinct `(identity, organization)` pair;
3. every submission remains subject to the existing key usage, class, gap,
   validity, revocation, artifact, claim, candidate, and signature checks; and
4. one key or identity cannot be replayed under another allowed authority class
   to manufacture quorum.

The current contract requires every issuer submission to attest the complete
required claim set for its gap. G10 therefore implements co-attestation: every
named authority class signs the same complete claim boundary, while attaching
the artifacts it is competent to issue. A later contract revision may divide
claims by authority class, but it must not weaken full-class participation.

Partial bundles remain useful for collection and diagnostics. They return the
missing gaps and missing issuer authority classes, but cannot become eligible
and cannot produce `all_authority_owned_gaps_closed=true`.

### Final review roster digest

For a final accepted bundle, the reviewer list is an ordered final roster. G10
computes `hepta.external-evidence-review-set.v1` over, for every reviewer:

- identity;
- organization;
- authority class;
- key ID;
- decision;
- sorted reviewed gap IDs; and
- signed timestamp.

The list order is part of the digest. Adding, removing, replacing, or reordering
a reviewer changes the digest.

### Acceptance context digest

G10 computes `hepta.external-evidence-acceptance-context.v1` over:

- acceptance state;
- `reviewed_at`;
- `decision_reference`;
- limitations; and
- the final review-set digest.

The bundle digest is deliberately excluded to avoid a signature cycle.

### Signed closure manifest

Every final review artifact must be UTF-8 JSON and contain:

```json
{
  "closure_manifest": {
    "schema_version": 1,
    "review_set_digest": "<64 lowercase hex>",
    "acceptance_context_digest": "<64 lowercase hex>"
  }
}
```

The existing reviewer Ed25519 statement already signs `review_uri` and
`review_sha256`. Therefore the review artifact hash cryptographically binds the
closure manifest without changing the G9 reviewer canonicalization or
invalidating the existing signature profile.

All final reviewers must carry the same two digests. Validation first verifies
the ordinary reviewer identity, authority, timing, review artifact hash, and
Ed25519 signature. It then recomputes the final roster and acceptance context
from the bundle and requires every signed artifact manifest to match.

This produces a co-signed final set:

- removing a rejecting or limiting review changes the roster digest;
- adding or replacing a reviewer changes the roster digest;
- reordering reviews changes the roster digest;
- changing accepted/rejected state, review time, decision reference, or
  limitations changes the acceptance-context digest; and
- recomputing the bundle self-hash cannot repair any mismatch.

The rule is applied whenever a bundle has the complete issuer authority set and
declares `accepted`, even if a caller omits `--require-complete`. No API path may
return `all_authority_owned_gaps_closed=true` without verified manifests.

### Scope of the guarantee

The manifest proves integrity of the final roster that its members co-signed.
It cannot discover a review that was never admitted to that roster. Selection
of the accountable reviewers, completeness of an external review register, and
organizational independence remain governance and external-authority
responsibilities. A future transparency-log integration may add global review
discovery without replacing this local cryptographic invariant.

## Required negative evidence

The deterministic suite must prove that:

- a complete bundle missing any named issuer class fails;
- the same key cannot fill two authority seats for one gap;
- the same identity and organization cannot fill two seats through different
  keys;
- a full distinct-authority bundle passes;
- removing a signed dissenting review and recomputing the bundle digest fails;
- adding, replacing, or reordering final reviewers fails unless every reviewer
  signs the new final roster;
- mutating final limitations or decision context fails;
- a missing, malformed, wrong-version, or mismatched closure manifest fails;
- partial evidence remains inspectable but never reports closure; and
- the external registry pin, key validity, evidence signatures, reviewer
  coverage, and independence rules remain in force.

## Alternatives rejected

- **Treat any allowed authority class as sufficient:** contradicts the named
  multi-authority contract and allows one key to impersonate a complete
  operational chain.
- **Require a key to list all classes:** still permits one omnipotent key to fill
  every seat.
- **Keep one submission per gap and add unsigned co-signer names:** names are not
  cryptographic participation.
- **Rely only on the bundle digest:** the curator controls that self-hash.
- **Sign each review independently without a roster:** allows post-sign removal.
- **Include review artifact hashes inside the roster digest:** creates a
  circular dependency because the artifacts contain the roster digest.
- **Require an external transparency service immediately:** useful later, but
  not necessary to close the repository-controlled final-roster deletion
  weakness.

## Consequences

A complete authority-owned package contains more submissions than gaps and may
contain multiple artifacts per gap. Operators must enroll narrowly scoped keys
for every named authority class and must prepare the complete reviewer roster
before final reviewer signatures are issued.

Final review artifacts become machine-readable review envelopes. They may
reference separate human-readable reports by content digest or opaque
access-controlled identifier.

G10 closes only repository-controlled quorum and final-set integrity. It does
not create a physical test, provider receipt, administrator readback, firmware
authorization, independent assurance report, production signing identity,
pilot result, store approval, or release decision.
