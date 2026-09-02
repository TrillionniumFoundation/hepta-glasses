# G10 trusted verifier and canonical contract binding

## Scope

This guide covers the implementation and verification of `HG-0080` and
`HG-0081`. It supplements the quorum and final-review controls in
`G10_AUTHORITY_QUORUM_AND_REVIEW_INTEGRITY.md`.

The controls apply to authority-bearing validation and signing. They do not
turn repository source, unit tests, or CI into E5–E7 evidence.

## Components

| Component | Responsibility |
|---|---|
| `runtime_policy.py` | Separates public current-time validation from the private deterministic test clock and rejects cryptographic executable overrides |
| `semantic_binding.py` | Installs contract-content-bound issuer, evidence-set, and reviewer canonical functions |
| `__init__.py` | Enforces installation order and exports only the public runtime validator |
| `cli.py` | Exposes no caller-selectable OpenSSL path and invokes the public validator |
| `validate_external_evidence.py` | Preserves historical test-fixture compatibility without changing executable CLI authority |
| `test_external_evidence_runtime_policy.py` | Exercises public clock and executable-injection negatives |
| `test_external_evidence_contract_binding.py` | Exercises same-revision semantic drift and revision/content mismatch negatives |

## Runtime validation state machine

```text
caller
  -> public validate_bundle
      -> reject supplied now
      -> reject custom openssl_binary
      -> capture current UTC time
      -> enter one validation_snapshot transaction
      -> read and validate contract/bundle/registry/evidence
      -> return result

unit-test fixture
  -> private _validate_bundle_at_for_tests
      -> require explicit fixed now
      -> reject custom openssl_binary
      -> enter the same validation_snapshot transaction
      -> run the same underlying policy
```

The private hook is intentionally absent from `__all__`. The executable script
uses `tools.external_evidence.cli.main`, whose module imported the public
acceptance alias after package initialization. Loading
`tools/validate_external_evidence.py` under the historical fixture module name
selects the private hook only for deterministic unit tests.

## Contract binding

The canonical contract object is read through the same bounded snapshot system
as every evidence object. Its canonical SHA-256 is derived with
`canonical_digest` and placed in a contract-binding object.

Every issuer preimage includes that object. Every reviewer preimage includes it
directly and also includes an evidence-set digest carrying the same binding.
Therefore:

- changing authority classes invalidates signatures;
- changing required claims or their class partition invalidates signatures;
- changing independence, review authority, physical-only rules, or closure
  states invalidates signatures;
- changing the closure rule invalidates signatures; and
- retaining the old revision label does not preserve signature validity.

The declared revision argument must match the revision in the exact contract
bytes. This prevents a signer or verifier from naming one revision while using
another object.

## Failure semantics

Public clock or OpenSSL override attempts fail before any evidence read. No
partial validation result is returned as success.

Contract revision/content disagreement raises `EvidenceError`. Contract file
replacement during one transaction remains subject to the G9 exact-object and
aggregate-snapshot controls. A contract changed between transactions is a new
semantic object and requires fresh issuer and reviewer signatures.

The private test hook does not bypass signature, key, time, artifact, custody,
quorum, claim-scope, or review-manifest validation. It controls only the
validation instant used by deterministic tests.

## Security boundary

Trusted runtime dependencies are:

- the operating-system kernel and filesystem primitives;
- a correct system UTC clock;
- the verifier Python process and source object;
- the installed canonical OpenSSL command and its runtime dependencies; and
- the externally protected trust-registry digest.

An arbitrary evidence submitter controls none of these. Host compromise,
malicious `PATH`, or replacement of the installed system OpenSSL is an
operational-host failure and must be handled by hardened release hosts,
provenance, and independent custody; it is not repaired by accepting a caller
path argument.

## Tests

Required tests include:

1. package validator rejects `now`;
2. direct `complete_closure.validate_bundle` rejects `now`;
3. package validator rejects custom `openssl_binary`;
4. executable parser rejects `--openssl-binary`;
5. compatibility in-memory verifier rejects custom OpenSSL;
6. private test hook requires `now` and rejects custom OpenSSL;
7. same-revision contract mutation changes submission, evidence-set, and review
   preimages; and
8. revision argument/current-contract mismatch fails.

The complete repository suite must also continue to pass every G8, G9, and
prior G10 test, both mobile builds, native tests, sanitizers, all-ref secret
scan, release-binary authority scan, and exact-head source-evidence generation.

## Operations

Evidence operators must regenerate every issuer and reviewer signature after
any canonical contract change. A contract revision label alone is not enough to
reuse a signature; the exact canonical contract digest is authoritative inside
the signed preimage.

Operators must invoke the canonical CLI without a crypto-binary override and on
a host whose clock and OpenSSL installation are controlled. Tests may use the
private fixed-clock hook only inside the repository qualification suite.

## Reopen conditions

Reopen `HG-0080` if any public package, module, compatibility, or CLI path can:

- supply validation time;
- select a different cryptographic executable;
- receive test-clock authority through a public export; or
- reach an unwrapped underlying validator.

Reopen `HG-0081` if an issuer or reviewer signature remains valid after any
canonical contract field changes without a corresponding fresh signature, or
if a stated revision can disagree with the contract bytes used by signing or
verification.
