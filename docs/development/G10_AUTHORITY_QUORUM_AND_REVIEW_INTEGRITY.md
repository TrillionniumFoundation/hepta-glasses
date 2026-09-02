# G10 authority quorum, claim scope, final-review integrity, and repository admission

## Status

- Plan and contract revision: `2026-09-02-g10-quorum-1`
- Policy ID: `hepta-external-complete-closure-v1`
- Extends: G9 authenticated external evidence
- Source branch: `work/hepta-g10-authority-quorum-review-integrity-20260902`
- Repository-actionable gaps: `HG-0076`, `HG-0077`, `HG-0078`, `HG-0079`
- Product claim ceiling: E0–E4 source only
- Merge state: Draft / do not merge until exact-head CI, artifact inspection,
  and an eligible non-pusher review succeed

## Problem statement

G9 made individual evidence and review statements non-self-issuable, but four
complete-closure gaps remained:

1. one submission from any allowed issuer class could satisfy a multi-authority
   gap;
2. requiring every class to sign every claim would force authorities to attest
   facts they do not own;
3. final reviewer signatures did not bind the complete reviewer roster or
   acceptance-level limitations; and
4. repository CI searched top-level `bundle.json` files but immutable accepted
   successors live below `successors/`.

G10 also requires that every import path reaches the same immutable validation
transaction and that recursive accepted-envelope discovery cannot promote a
file replaced between lexical inspection and descriptor open.

## Source map

| Area | Implementation |
|---|---|
| Versioned complete policy | `contracts/external-evidence-envelope-v1.json`, `tools/external_evidence/complete_closure.py` |
| Package entry points | `tools/external_evidence/__init__.py`, `tools/validate_external_evidence.py` |
| Existing crypto and custody | `submission.py`, `acceptance.py`, `trust.py`, `core.py`, `snapshot_io.py`, `signing.py`, `signing_io.py` |
| Multi-authority fixture | `services/qualification/external_evidence_test_support.py` |
| Closure attacks | `services/qualification/test_external_evidence_complete_closure.py` |
| Direct-entrypoint snapshot gate | `services/qualification/test_external_evidence_entrypoint_snapshot.py` |
| Committed-package gate | `services/qualification/test_external_evidence_repository.py` |
| Layer metadata | `services/qualification/test_g9_metadata.py`, `test_g10_metadata.py` |
| Normative design | `docs/adr/ADR-0008-authority-quorum-and-review-set-integrity.md` |
| Operator contract | `evidence/external/README.md` |
| Machine truth | `docs/G10_STATE.json`, `docs/G10_MODULES.json`, `docs/G10_GAP_LEDGER.json` |

## HG-0076: complete issuer authority quorum

For every gap in a complete bundle, validated submissions must cover every
`authority_class` named by the canonical contract. Multiple submissions per gap
are expected.

Within the same gap, every seat has a distinct trust-registry key ID and a
distinct `(identity, organization)` pair. Each key remains bound to usage,
class, allowed gaps, validity, revocation, public-key bytes, and normalized
Ed25519 SPKI. A broad key cannot fill another seat by changing only the class
label.

Partial collection returns `missing_gaps` and
`missing_issuer_authority_classes`; it never returns closure.

## HG-0078: version, claim partition, and entrypoint consistency

The signed contract revision is G10 and identifies the G9 predecessor. An old
G9-revision signature fails because `contract_revision` is in issuer and
reviewer signature preimages.

`required_claims_by_authority_class` is validated as a disjoint exhaustive
partition of each gap's `required_claims`. Every class has a non-empty scope.
Every required claim appears exactly once. An issuer submission must contain
exactly its assigned scope:

- missing class claims fail;
- claims owned by another class fail;
- false or non-boolean required claims fail through the G9 primitive; and
- the full gap claim boundary is satisfied only after every class-specific
  signature is present.

This separates real responsibilities. For example, the repository administrator
signs configuration claims while the API observer signs the fresh readback;
the credential provider signs revocation facts while the incident owner signs
scope and closure; signing, pilot, and store authorities sign different release
claims.

Validation returns `issuer_claim_scopes` so the accepted machine report records
the exact legal partition.

The immutable validation wrapper is installed on
`complete_closure.validate_bundle` itself before aliases are exported. The
acceptance-module alias, package-level validator, command-line wrapper, and an
explicit direct import therefore reference the same aggregate-bounded snapshot
entrypoint. A direct submodule import cannot fall back to an unwrapped policy
function and re-read mutable evidence between phases.

## HG-0077: final review-set and acceptance integrity

The final ordered reviewer roster digest covers policy ID/revision and each
reviewer's identity, organization, authority class, key ID, decision, reviewed
gaps, and signed time.

The acceptance-context digest covers policy ID/revision, state, `reviewed_at`,
`decision_reference`, limitations, and the roster digest.

Every accepted review artifact contains:

```json
{
  "closure_manifest": {
    "schema_version": 1,
    "policy_id": "hepta-external-complete-closure-v1",
    "policy_revision": "2026-09-02-g10-quorum-1",
    "review_set_digest": "...",
    "acceptance_context_digest": "..."
  }
}
```

The artifact digest is already inside the reviewer Ed25519 statement. Removing,
adding, replacing, or reordering a final reviewer, changing acceptance state or
limitations, or substituting another policy revision invalidates every
surviving manifest. The requirement applies to every `accepted` bundle even if
a caller does not request complete validation.

This guarantees the final roster its members co-signed. It does not discover a
review never admitted to the roster; accountable reviewer selection and any
external transparency register remain governance gates.

## HG-0079: recursive committed accepted-envelope gate

Repository qualification recursively inspects every bounded regular file under
`evidence/external/`. It identifies an accepted envelope by canonical
`contract_id` and `acceptance.state`, not filename, extension, or depth.

Candidate discovery first captures the lexical file identity, then opens the
same name with `O_NOFOLLOW`, and requires device, inode, mode, size,
modification time, and change time to match. The complete bounded read is made
through that one descriptor, whose identity is checked again afterward. A
symbolic link, ordinary replacement between `lstat` and `open`, special object,
oversized file, unsupported no-follow API, metadata mutation, or short read is
never promoted into the accepted-envelope set.

For every stable match the gate locates the enclosing custody root and requires:

- a trust registry and artifact root;
- `require_complete=true`;
- `require_accepted=true`;
- the protected out-of-band registry SHA-256;
- empty missing gap/class sets; and
- verified final review-set integrity.

An accepted successor named `opaque.payload` is still discovered. Intermediate,
rejected, template, artifact, key, signature, and ordinary review files do not
match the envelope content identity.

## Validation sequence

1. Snapshot the versioned contract and prove its complete-closure profile.
2. Prove authority class and claim-scope maps cover the same exact gap set.
3. Prove each gap's class scopes are disjoint and exhaustive.
4. Snapshot bundle, registry, keys, artifacts, signatures, and reviews through
   G9's bounded exact-object custody.
5. For every submission, derive its class-scoped contract view and run all G9
   cryptographic and artifact validation.
6. Reject reused keys or identity/organization seats within a gap.
7. Reject missing gaps or issuer classes for complete admission.
8. Verify reviewer identity, authority, timing, artifact hash, Ed25519
   signature, approval coverage, and independence.
9. Recompute final roster and acceptance digests and verify every signed
   manifest.
10. Set closure true only after all steps pass.

## Test matrix

The suite includes:

- full distinct-authority positive closure;
- missing `github_api_observer`;
- one key filling two HG-0017 seats;
- cross-scope claim assertion;
- G9 revision downgrade attempt;
- wrong manifest policy revision;
- signed dissent removal after bundle re-hash;
- final reviewer reorder;
- post-sign limitation mutation;
- direct `complete_closure` import without an active snapshot;
- acceptance-module and policy-module entrypoint identity;
- opaque-extension accepted successor discovery;
- static symbolic-link discovery rejection;
- regular-file replacement between `lstat` and descriptor open; and
- inherited key substitution, expiry, revocation, parser, timing, alias,
  synthetic-physical, filesystem-replacement, and signing-custody negatives.

## Reopen conditions

Reopen the affected G10 gap if any path can report closure while:

- a named issuer class is absent;
- one key or identity/organization pair fills multiple seats;
- a class omits its assigned claim or signs another class's claim;
- the contract revision or policy profile is not bound to signatures;
- a final review or acceptance field changes after signing;
- an accepted envelope can avoid repository CI by nesting, renaming, symbolic
  linking, or replacement during discovery; or
- another public or direct module entrypoint invokes an unwrapped or weaker
  complete validator.

## External boundary

G10 does not mark any inherited row `CLOSED_VERIFIED`. Physical G1
qualification, independent assurance, signed binaries and rollout, provider
credential revocation, production model/realtime/OAuth/capability services,
KMS/HSM and platform attestation, vendor firmware authority, canonical main
protection, production Android speech, and authenticated exact-head acceptance
still require their real authority-issued evidence.
