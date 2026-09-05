# ADR-0008: Version complete-closure policy, partition issuer claims, and bind the final review set

- Status: accepted for G10 source
- Date: 2026-09-02
- Extends: `ADR-0004-external-evidence-authentication.md`
- Extends: `ADR-0007-evidence-object-identity-and-bounded-custody.md`
- Plan and contract revision: `2026-09-02-g10-quorum-1`
- Policy ID: `hepta-external-complete-closure-v1`

## Context

G9 authenticates each evidence submission and reviewer decision under an
externally pinned Ed25519 trust registry. It binds the candidate, claims,
artifacts, limitations, decision, reviewed gaps, and evidence-set digest. Four
complete-closure weaknesses remained.

First, the contract names multiple issuer classes for most product gaps, but the
G9 validator accepted one submission per gap and therefore treated any one
allowed class as sufficient.

Second, forcing every class to sign every claim would be an unusable repair. A
credential provider cannot truthfully approve the incident owner's risk
decision; a store authority cannot attest the signing authority's key custody;
an API observer cannot claim to have configured branch protection. Claims need
a versioned, exact authority scope.

Third, reviewer signatures did not bind the final reviewer roster or
acceptance-level state and limitations. A curator could delete a signed dissent,
recompute the unsigned bundle digest, and leave surviving reviewer signatures
valid.

Fourth, the immutable signer writes accepted successors below `successors/`,
while repository CI previously searched only one top-level `bundle.json` name.
A committed accepted successor could therefore evade protected-pin validation.

A further implementation boundary follows from those decisions: the complete
policy is not effective if a caller can import an unwrapped submodule function,
or if repository discovery inspects a regular file and later reopens the same
name after it has been replaced.

## Decision

### Versioned contract and downgrade resistance

The canonical external-evidence contract revision is
`2026-09-02-g10-quorum-1` and explicitly identifies
`2026-09-02-g9-authenticated-1` as its predecessor. The contract declares the
complete-closure policy ID, all-class quorum mode, exact class-scoped claim
mode, distinct-seat rules, review-manifest schema, and digest statement types.

Issuer and reviewer canonical Ed25519 preimages already contain
`contract_revision`; consequently, a G10-signed statement fails under the older
G9 revision. Review-set and acceptance-context digest preimages additionally
contain the G10 policy ID and revision. The signed review artifact repeats both
values. A verifier cannot silently interpret a G10 package under the weaker G9
semantics.

### Canonical validation entrypoint

The immutable, aggregate-bounded validation wrapper is installed directly on
`complete_closure.validate_bundle` before any public aliases are exported. The
acceptance-module alias, package-level API, command-line wrapper, and explicit
submodule import therefore resolve to the same wrapped function.

Wrapping only `_acceptance.validate_bundle` is insufficient: a caller could
otherwise import `tools.external_evidence.complete_closure.validate_bundle`
and invoke the policy without the one-transaction byte snapshot. A regression
test replaces the policy module's `read_object` function with a probe and proves
that a direct module call already has an active snapshot and that the snapshot
is released after failure.

### Complete issuer quorum

A bundle may contain multiple independently signed submissions for one gap.
Complete closure requires every authority class listed for that gap.
Within the same gap, each seat uses:

1. a distinct trust-registry key ID; and
2. a distinct `(identity, organization)` pair.

One broad key or identity cannot fill multiple seats merely by changing the
class string. All existing key usage, class, gap, validity, revocation,
artifact, candidate, time, and signature checks remain active.

### Exact class-scoped claim partition

`required_claims_by_authority_class` is a disjoint, exhaustive partition of
`required_claims` for each gap. At validator startup, G10 proves:

- the mapping covers exactly the allowed gaps;
- every named issuer class has one non-empty scope;
- no claim is assigned twice;
- no required claim is unassigned; and
- no unknown claim is introduced.

Each issuer submission must contain exactly its class scope. Missing claims and
cross-scope claims fail before acceptance. The full gap claim boundary is true
only after every class-specific signed submission is present. This lets each
real authority attest only facts it owns while preserving complete coverage.

Partial packages remain inspectable and report both missing gaps and missing
classes, but can never become eligible or closed.

### Final review roster digest

The final reviewer list is ordered. G10 computes
`hepta.external-evidence-review-set.v1` over the policy ID/revision and, for
each reviewer:

- identity and organization;
- authority class and key ID;
- decision;
- sorted reviewed gap IDs; and
- signed timestamp.

Adding, removing, replacing, or reordering a reviewer changes the digest.

### Acceptance context digest

G10 computes `hepta.external-evidence-acceptance-context.v1` over the policy
ID/revision, acceptance state, `reviewed_at`, `decision_reference`, limitations,
and final review-set digest. The bundle digest is excluded to avoid a signature
cycle.

### Signed closure manifest

Every accepted review artifact must be UTF-8 JSON containing:

```json
{
  "closure_manifest": {
    "schema_version": 1,
    "policy_id": "hepta-external-complete-closure-v1",
    "policy_revision": "2026-09-02-g10-quorum-1",
    "review_set_digest": "<64 lowercase hex>",
    "acceptance_context_digest": "<64 lowercase hex>"
  }
}
```

The reviewer Ed25519 statement signs `review_uri` and `review_sha256`, so it
cryptographically binds this manifest without creating a digest cycle. Every
final reviewer must carry the same roster and context digests. The manifest is
required for every `accepted` bundle, not only when a caller passes
`--require-complete`.

Removing a dissent, adding or replacing a reviewer, reordering the list, or
changing accepted state, review time, decision reference, or limitations makes
every surviving manifest inconsistent. Recomputing the curator-controlled
bundle digest cannot repair it.

The manifest proves integrity of the final roster its members co-signed. It
cannot discover a review never admitted to that roster; reviewer selection,
external review registries, and organizational independence remain governance
responsibilities.

### Recursive committed-package admission

Repository qualification recursively inspects every bounded regular file under
`evidence/external/`. It identifies an authority envelope by canonical
`contract_id` plus `acceptance.state == "accepted"`, not by filename, suffix, or
directory depth.

Discovery captures the lexical object's device, inode, mode, size,
modification-time, and change-time identity. It then opens the same lexical name
with `O_NOFOLLOW`, requires the opened identity to equal the captured identity,
performs the complete bounded read through that one descriptor, and requires
the descriptor identity and byte count to remain stable afterward. A static
link, a regular-file or link replacement between `lstat` and `open`, a special
object, an oversized object, a platform without no-follow support, a metadata
mutation, or a short read is never promoted into the accepted-envelope set.

Every discovered envelope is mapped to the nearest custody root containing
`trust-registry.json` and `artifacts/`, then revalidated with:

- `require_complete=true`;
- `require_accepted=true`; and
- protected `HEPTA_EXTERNAL_TRUST_REGISTRY_SHA256`.

An opaque filename or immutable successor path cannot hide an accepted package
from CI, and a replacement race cannot inject one after lexical inspection.

## Required negative evidence

The deterministic suite proves that:

- a complete bundle missing any named issuer class fails;
- one key cannot fill two authority seats for one gap;
- a class cannot omit its assigned claim or assert another class's claim;
- the claim scopes are a disjoint exhaustive partition;
- an issuer signature created under the G9 revision fails under G10;
- a full distinct-authority bundle passes;
- removing a signed dissent and recomputing the bundle digest fails;
- adding, replacing, or reordering final reviewers fails unless every reviewer
  signs the new roster;
- mutating final limitations or decision context fails;
- a missing, malformed, wrong-policy, wrong-version, or mismatched manifest
  fails;
- a direct complete-closure submodule call has an active immutable snapshot;
- the acceptance alias and policy module expose one identical wrapped function;
- an accepted envelope with an opaque extension is still discovered;
- a static repository symlink is never followed;
- a regular file replaced between lexical inspection and open is rejected; and
- external pin, key validity, evidence signatures, reviewer coverage,
  independence, and filesystem custody remain in force.

## Alternatives rejected

- **Any allowed class is sufficient:** collapses a multi-party boundary.
- **One omnipotent key lists all classes:** produces labels, not independent
  participation.
- **Every class signs every claim:** forces authorities to attest facts they do
  not own and makes legitimate closure impracticable.
- **Unsigned co-signer names:** provide no proof of participation.
- **Only the bundle digest protects reviews:** the curator controls that hash.
- **Independent review signatures without a roster:** permit post-sign removal.
- **Reuse G9 contract revision:** enables semantic downgrade and ambiguous
  verification.
- **Wrap only a package alias:** leaves a direct submodule policy call outside
  the immutable transaction.
- **Scan only `*/bundle.json`:** misses immutable successors and trusts naming
  conventions.
- **Use `lstat()` and then `Path.read_text()`:** re-resolves a mutable name and
  permits replacement between check and read.
- **Silently omit `O_NOFOLLOW` on unsupported platforms:** turns a fail-closed
  source gate into link-following behavior.
- **Require a transparency service immediately:** useful for global review
  discovery, but not necessary to close local final-roster deletion.

## Consequences

A complete package contains more submissions than gaps. Evidence operators must
provision narrowly scoped keys for every named class, collect only class-owned
claims and artifacts, freeze the final reviewer roster, generate the G10
manifest, and then obtain reviewer signatures.

Accepted packages committed at any successor depth trigger protected-pin CI
validation. Intermediate or rejected packages remain non-authoritative.
Repository discovery now requires Linux/POSIX-style no-follow semantics; a
platform unable to provide them does not classify a file as an accepted
candidate.

G10 closes repository-controlled quorum, claim scope, policy downgrade,
review-set deletion, entrypoint aliasing, and package-discovery gaps. It does
not create physical tests, provider receipts, administrator readback, firmware
authorization, independent assurance, production signatures, pilot results,
store approvals, or release authority.
