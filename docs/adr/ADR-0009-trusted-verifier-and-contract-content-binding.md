# ADR-0009: Authority validation owns its clock, crypto executable, environment, and canonical contract identity

- Status: accepted for G10 source
- Date: 2026-09-02
- Extends: `ADR-0004-external-evidence-authentication.md`
- Extends: `ADR-0008-authority-quorum-and-review-set-integrity.md`
- Plan revision: `2026-09-02-g10-quorum-1`
- Source gaps: `HG-0080`, `HG-0081`

## Context

An evidence package is untrusted input. The verifier process, operating-system
clock, cryptographic implementation, executable pathname, and subprocess
environment are part of the authority boundary.

The Python validation API originally accepted a caller-supplied `now` value and
an arbitrary `openssl_binary`; the executable CLI also exposed
`--openssl-binary`. G10 removed those explicit parameters, but a literal command
name was still insufficient: `subprocess` resolved `openssl` through the
invoking process `PATH`, and inherited `OPENSSL_CONF`, `OPENSSL_MODULES`,
dynamic-loader variables, and other environment state. A same-name executable
or injected provider/library could therefore remain caller selected despite the
API rejecting a custom pathname.

Issuer and reviewer Ed25519 preimages also previously contained the
human-selected `contract_revision` string but not the canonical content of the
contract. A contract file could retain the same revision while changing
authority classes, claim partitions, review requirements, or closure
semantics. Previously signed statements would not distinguish those byte-level
semantics.

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
does not grant cryptographic-executable or environment selection.

### Validation and signing pin one trusted OpenSSL object

Authority-bearing validation and signing accept only the logical selector
`openssl`, but do not resolve it through `PATH`. Package initialization installs
`openssl_policy.py` before trust, signature, and private-key modules import or
execute their helpers.

The policy supports exactly `/usr/bin/openssl`. Before every cryptographic
subprocess it requires:

1. `/`, `/usr`, and `/usr/bin` to be real directories owned by UID 0 and not
   group- or world-writable;
2. `/usr/bin/openssl` to be a real regular file owned by UID 0, not group- or
   world-writable, and executable;
3. no-follow opening of the final executable; and
4. matching lexical-before, opened-descriptor, and lexical-after device, inode,
   mode, size, modification-time, and change-time identity.

Unsupported hosts fail closed instead of falling back to a caller-selected
binary. The CLI declares no `--openssl-binary`; package and compatibility APIs
reject custom values; shell execution, `executable=` substitution, and a
caller-supplied subprocess environment are prohibited.

Every OpenSSL invocation replaces the caller environment with a minimal map:

```text
HOME=/nonexistent
LANG=C
LC_ALL=C
OPENSSL_CONF=/dev/null
PATH=/usr/bin:/bin
TZ=UTC
```

Consequently `OPENSSL_MODULES`, `LD_PRELOAD`, `LD_LIBRARY_PATH`,
`DYLD_INSERT_LIBRARIES`, `DYLD_LIBRARY_PATH`, caller `PATH`, and other inherited
configuration or loader injection variables are absent. Public-key parsing,
normalized DER-SPKI calculation, signature verification, private-key type
checks, and signing all use this same policy.

The operating-system kernel, root-owned system directories, the bytes and
runtime dependencies of the checked system executable, and the verifier
process itself remain trusted host dependencies. A hostile kernel, root-level
replacement, or arbitrary code already executing inside the verifier process
is outside this source contract and requires host attestation and release
custody.

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
2. install the absolute-path OpenSSL resolver and sanitized subprocess policy
   for core validation and signing I/O;
3. patch public-key normalization to consume pinned bytes;
4. install contract-content-bound canonical issuer/reviewer functions into
   `core`, `submission`, and `acceptance` module globals;
5. import the G10 complete-closure policy; and
6. install the trusted current-time wrapper on the policy function itself.

The validator and signer therefore derive identical preimages from identical
contract bytes and execute the same checked cryptographic object under the same
minimal environment.

## Required negative evidence

The deterministic suite proves that:

- package and direct policy entrypoints reject caller-supplied time;
- package and compatibility verification reject custom OpenSSL selection;
- the executable parser rejects `--openssl-binary`;
- the private test hook requires a time and still rejects custom OpenSSL;
- the resolver returns only root-owned, non-writable `/usr/bin/openssl`;
- a same-name executable placed first on caller `PATH` is not executed during
  private-key validation, signing, or signature verification;
- loader and OpenSSL configuration variables are absent from the subprocess
  environment;
- changing contract semantics while keeping the same revision changes issuer,
  evidence-set, and reviewer digests; and
- a revision argument that disagrees with the current contract bytes fails.

All inherited expiry, revocation, future-time, wrong-key-type, random-signature,
key-alias, parser, custody, quorum, claim-scope, and review-roster tests remain
active.

## Alternatives rejected

- **Trust caller-supplied `now`:** lets an untrusted invocation reinterpret
  expired or revoked authority as current.
- **Accept only the command name `openssl`:** still delegates executable choice
  to caller-controlled `PATH`.
- **Resolve once with `shutil.which`:** still consumes `PATH` and does not
  authenticate the selected object or its ancestors.
- **Inherit the process environment:** permits OpenSSL configuration, provider,
  and dynamic-loader injection.
- **Expose an absolute OpenSSL path for convenience:** lets an invocation select
  the program responsible for declaring its own signatures valid.
- **Use a test environment variable:** production callers can set it and it does
  not provide a capability boundary.
- **Bind only a revision string:** a mutable contract can retain the label.
- **Bind only selected contract fields:** omitted semantics can still drift.
- **Store a self-referential digest inside the contract:** creates unnecessary
  canonicalization and update complexity.
- **Rely only on source review:** useful, but does not let external signatures
  identify the exact rules they accepted.

## Consequences

Every new issuer or reviewer signature depends on the exact canonical contract
content. Contract changes invalidate existing signatures even when a maintainer
retains the revision label. Evidence operators must re-sign after any contract
change.

Deterministic validation time remains a test-only capability. Operational
callers must execute the canonical CLI or package API on a supported host with a
correct UTC clock and a root-owned, non-writable `/usr/bin/openssl`. Caller
`PATH`, OpenSSL configuration, module paths, and dynamic-loader variables no
longer select the cryptographic implementation. Hosts that cannot establish
this invariant fail closed.

Host attestation, reproducible verifier packaging, system-binary provenance,
and external release custody remain separate operational or E5–E7 concerns.
These source controls do not produce physical-device reports, provider
receipts, administrator readback, firmware authority, independent assurance,
signed binaries, pilot telemetry, store approval, or product-release
authority.
