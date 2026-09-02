# ADR-0009: Authority validation owns its clock, crypto executable, and canonical contract identity

- Status: accepted for G10 source
- Date: 2026-09-02
- Extends: `ADR-0004-external-evidence-authentication.md`
- Extends: `ADR-0008-authority-quorum-and-review-set-integrity.md`
- Plan revision: `2026-09-02-g10-quorum-1`
- Source gaps: `HG-0080`, `HG-0081`

## Context

An evidence package is untrusted input. The verifier process, operating-system
clock, and cryptographic implementation are part of the authority boundary.
Two source-level escape paths remained after G10 quorum and review-set closure.

First, the Python validation API accepted a caller-supplied `now` value and an
arbitrary `openssl_binary`. The executable CLI also exposed
`--openssl-binary`. A caller could therefore attempt to validate at a time
before key expiry or revocation, or route key parsing and signature checks to an
attacker-controlled executable.

Second, issuer and reviewer Ed25519 preimages contained the human-selected
`contract_revision` string but not the canonical content of the contract. A
contract file could retain the same revision while changing authority classes,
claim partitions, review requirements, or closure semantics. Previously signed
statements would not distinguish those byte-level semantics.

## Decision

### Public validation owns current time

The package-level validator, direct `complete_closure` module entrypoint, and
executable CLI obtain the current timezone-aware UTC time inside the trusted
runtime wrapper. They reject a supplied `now` keyword before reading the
contract, bundle, registry, key, artifact, review, or signature.

The underlying deterministic validator remains available only through a
private `_validate_bundle_at_for_tests` hook. It is absent from `__all__` and is
used by the historical qualification fixture loaded under its dedicated test
module identity. The hook requires an explicit timezone-aware test time and
does not grant cryptographic-executable selection.

This separation prevents production admission from inheriting test clock
authority while preserving deterministic expiry, revocation, ordering, and
future-time tests.

### Public validation fixes cryptographic command selection

Authority-bearing validation accepts only the literal canonical command
`openssl`. The CLI no longer declares `--openssl-binary`. Package and direct
module entrypoints reject any custom value before evidence reads. The
compatibility in-memory verification helper applies the same restriction.

The operating system, process, `PATH`, and installed OpenSSL remain trusted
runtime dependencies. A compromised kernel, verifier process, environment, or
system OpenSSL installation is outside this source contract and must be
controlled by release-host hardening and provenance. This ADR removes the
explicit untrusted argument surface; it does not claim to attest the host.

### Canonical contract bytes are signed

Package initialization installs canonical statement functions that compute a
contract-binding statement from the exact object returned by the stable,
bounded contract reader:

```json
{
  "statement_type": "hepta.external-evidence-contract-binding.v1",
  "contract_id": "hepta-external-evidence-envelope-v1",
  "contract_revision": "2026-09-02-g10-quorum-1",
  "contract_sha256": "<canonical JSON SHA-256>"
}
```

The binding is included in:

1. every issuer submission Ed25519 preimage;
2. the evidence-set digest; and
3. every reviewer Ed25519 preimage.

Canonical JSON uses recursively sorted keys, UTF-8, no insignificant
whitespace, finite numbers only, and the existing `canonical_digest` helper.
The complete contract object is covered; no mutable field is excluded.

The caller-supplied revision argument must equal the revision in the current
contract bytes. A mismatch fails before statement generation or signature
verification.

### Installation order

`tools/external_evidence/__init__.py` performs this order:

1. install immutable and aggregate-bounded filesystem snapshots;
2. patch public-key normalization to consume pinned bytes;
3. install contract-content-bound canonical issuer/reviewer functions into
   `core`, `submission`, and `acceptance` module globals;
4. import the G10 complete-closure policy; and
5. install the trusted runtime wrapper on the policy function itself.

The signer imports the patched core functions after package initialization. The
validator and signer therefore derive identical preimages from identical
contract bytes.

## Required negative evidence

The deterministic suite proves that:

- package and direct policy entrypoints reject caller-supplied time;
- package and compatibility verification reject custom OpenSSL selection;
- the executable parser rejects `--openssl-binary`;
- the private test hook requires a time and still rejects custom OpenSSL;
- changing contract semantics while keeping the same revision changes issuer,
  evidence-set, and reviewer digests; and
- a revision argument that disagrees with the current contract bytes fails.

All inherited expiry, revocation, future-time, wrong-key-type, random-signature,
key-alias, parser, custody, quorum, claim-scope, and review-roster tests remain
active.

## Alternatives rejected

- **Trust caller-supplied `now`:** lets an untrusted invocation reinterpret
  expired or revoked authority as current.
- **Expose an OpenSSL path for convenience:** lets an invocation select the
  program responsible for declaring its own signatures valid.
- **Use a test environment variable:** production callers can set it and it
  does not provide a capability boundary.
- **Bind only a revision string:** a mutable contract can retain the label.
- **Bind only selected contract fields:** omitted semantics can still drift.
- **Store a self-referential digest inside the contract:** creates unnecessary
  canonicalization and update complexity.
- **Rely only on source review:** useful, but does not let external signatures
  identify the exact rules they accepted.

## Consequences

Every new issuer or reviewer signature now depends on the exact canonical
contract content. Contract changes invalidate existing signatures even when a
maintainer accidentally or maliciously retains the revision label. Evidence
operators must re-sign after any contract change.

Deterministic validation time is a test-only capability. Operational callers
must execute the canonical CLI or package API on a trusted host with a correct
UTC clock and trusted OpenSSL installation. Host attestation, reproducible
verifier packaging, and external release custody remain separate operational or
E5–E7 concerns.

These controls close repository-actionable runtime and semantic-binding gaps.
They do not produce physical-device reports, provider receipts, administrator
readback, firmware authority, independent assurance, signed binaries, pilot
telemetry, store approval, or product-release authority.
