# G10 authority quorum and final-review integrity closure

## Status

- Plan revision: `2026-09-02-g10-quorum-1`
- Extends: G9 authenticated external evidence
- Source branch: `work/hepta-g10-authority-quorum-review-integrity-20260902`
- Repository-actionable gaps: `HG-0076`, `HG-0077`
- Product claim ceiling: E0–E4 source only
- Merge state: Draft / do not merge until exact-head CI, artifact inspection,
  and an eligible non-pusher review succeed

## Problem statement

G9 made individual evidence and review statements non-self-issuable, but the
complete bundle admission rule still had two gaps:

1. one submission from any allowed issuer class could satisfy a gap whose
   contract names several accountable classes; and
2. final reviewer signatures did not bind the complete reviewer roster or the
   acceptance-level limitations and decision context.

The first defect could collapse a multi-party product boundary into one broadly
authorized key. The second could allow a bundle curator to delete a signed
dissenting or limiting review and recompute the local bundle digest.

## Source map

| Area | Implementation |
|---|---|
| Complete closure policy | `tools/external_evidence/complete_closure.py` |
| Package entry-point installation | `tools/external_evidence/__init__.py` |
| Existing issuer/reviewer crypto | `tools/external_evidence/submission.py`, `acceptance.py`, `trust.py`, `core.py` |
| Multi-authority fixture | `services/qualification/external_evidence_test_support.py` |
| Positive and hostile tests | `test_external_evidence.py`, `test_external_evidence_complete_closure.py`, `test_external_evidence_adversarial.py`, `test_external_evidence_review_order.py` |
| Normative design | `docs/adr/ADR-0008-authority-quorum-and-review-set-integrity.md` |
| Operator contract | `evidence/external/README.md` |
| Machine truth | `docs/G10_STATE.json`, `docs/G10_MODULES.json`, `docs/G10_GAP_LEDGER.json` |

## HG-0076: complete issuer authority quorum

### Invariant

For every gap in a complete bundle, the set of validated submission
`authority_class` values must cover the complete class set in the canonical
contract.

Within the same gap, each submission must have:

- a distinct trust-registry key ID;
- a distinct identity and organization pair;
- a key authorized for exactly the stated usage, class, gap, time, and
  revocation state;
- all required claims set to true;
- at least one bounded, digest-verified, secret-scanned artifact; and
- a valid Ed25519 attestation over the exact candidate and submission.

### Failure semantics

The validator returns missing class data for partial collection. With
`require_complete=true`, any missing class raises a stable fail-closed error
before acceptance is considered.

Duplicate key or identity use within one gap fails regardless of
`require_complete`. A bundle cannot fill two seats by changing only the
authority-class string.

### Data returned

Successful validation adds:

```text
complete_closure_policy
issuer_authority_coverage
missing_issuer_authority_classes
```

`eligible_for_review` and `all_authority_owned_gaps_closed` require an empty
missing-class map.

## HG-0077: final review-set integrity

### Review projection

The final ordered roster digest covers identity, organization, authority class,
key ID, decision, reviewed gaps, and signed time for every reviewer.

### Acceptance projection

The final acceptance digest covers state, `reviewed_at`,
`decision_reference`, limitations, and the roster digest.

### Review artifact contract

Every final reviewer must sign a review artifact containing the same
`closure_manifest`:

```json
{
  "closure_manifest": {
    "schema_version": 1,
    "review_set_digest": "...",
    "acceptance_context_digest": "..."
  }
}
```

The review artifact can also contain a human summary and references to a
separate report. Its exact bytes are already hashed in the reviewer object, and
that hash is already inside the Ed25519 reviewer statement.

### Validation order

1. Parse and snapshot the bundle, registry, public keys, artifacts, signatures,
   and review artifacts.
2. Verify every issuer submission and collect gap/class coverage.
3. Fail complete admission if any gap or class is absent.
4. Verify every reviewer identity, class, time, artifact hash, signature,
   approval coverage, and independence rule.
5. Recompute the ordered roster digest.
6. Recompute the acceptance context digest.
7. Parse every final review artifact and require matching schema-v1 manifests.
8. Set closure true only after all checks pass.

### Reopen conditions

Reopen `HG-0077` if any path can return closure while:

- a final reviewer is removed, added, replaced, or reordered after signing;
- an acceptance limitation, state, review time, or decision reference changes;
- a review artifact is non-JSON, lacks the manifest, or binds another roster;
- a partial bundle bypasses the manifest requirement; or
- another package entry point still invokes the older G9 complete validator.

## Test matrix

The suite includes:

- full multi-authority positive closure;
- missing `github_api_observer` negative;
- one key filling two HG-0017 seats negative;
- signed dissent removal negative;
- final reviewer reorder negative;
- acceptance limitation mutation negative;
- manifest digest output assertions;
- inherited key substitution, expiry, revocation, parser, timing, alias,
  filesystem replacement, signing custody, and synthetic-physical negatives.

## External boundary

G10 does not mark any inherited row `CLOSED_VERIFIED`. The following still
require real authority-issued evidence: physical G1 qualification, independent
assurance, signed binaries and rollout, provider credential revocation,
production model/realtime/OAuth/capability services, KMS/HSM and platform
attestation, vendor firmware authority, canonical main protection, production
Android speech, and authenticated exact-head governance acceptance.
