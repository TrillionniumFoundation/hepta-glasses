# G9 filesystem and signing custody hardening

Status: source candidate; exact-head E4 and independent review remain required.

Plan revision: `2026-09-02-g9-authenticated-1`

Normative decisions:

- `docs/adr/ADR-0004-external-evidence-authentication.md`
- `docs/adr/ADR-0006-external-evidence-filesystem-custody.md`
- `docs/adr/ADR-0007-evidence-object-identity-and-bounded-custody.md`

## Purpose

Close the residual source-controlled race conditions discovered after the first G9 filesystem-custody implementation. This change does not modify the meaning of E5–E7, does not accept any authority-owned evidence, and does not change the inherited 12-gap product boundary.

## Closed source defects

### Ordinary directory replacement

The earlier descriptor walk rejected symbolic-link components but did not prove that an ordinary directory opened under a checked name was the same directory object selected during scope resolution. Validation now captures and verifies device/inode/type identities for every ancestor directory before accepting the final file.

### Public-key phase drift

Registry byte hashing and key verification already used pinned bytes, but normalized DER-SPKI hashing reopened the authority path through OpenSSL. DER normalization now operates only on a private temporary copy of the pinned bytes. Byte digest, Ed25519 type check, SPKI uniqueness, and signature verification therefore share one key snapshot.

### Aggregate snapshot amplification

The top-level validation transaction now has a 512 MiB cumulative cache ceiling. Per-file maxima remain in force. The validator rejects a package when admitting another distinct input would exceed the transaction budget.

### Signing input and bundle replacement

Private-key inspection and signing now use one descriptor-captured key snapshot. The original key pathname is never reopened for the signing phase.

The input bundle is captured with its bytes and exact filesystem identities. Backwards-compatible in-place updates are staged into one mode-0600 file and replace only the exact unchanged input name through descriptor-relative atomic replacement. The preferred `--output-bundle-uri` mode creates a new immutable bundle successor and leaves the input unchanged.

## Implementation map

| Responsibility | Source |
|---|---|
| Validation transaction, URI canonicalization, object identity and aggregate budget | `tools/external_evidence/snapshot_io.py` |
| Snapshot-backed trust normalization | `tools/external_evidence/__init__.py`, `tools/external_evidence/trust.py` |
| Descriptor-bound private key, signatures and bundle output | `tools/external_evidence/signing_io.py` |
| Submission/reviewer/finalize operations and CLI | `tools/external_evidence/signing.py`, `tools/sign_external_evidence.py` |
| Validation hostile tests | `services/qualification/test_external_evidence_filesystem_hardening.py` |
| Signing hostile tests | `services/qualification/test_external_evidence_signer_custody.py` |

## Required invariants

1. One canonical scoped URI has one lexical cache identity.
2. Every opened ancestor and final input object must match the identity captured before consumption.
3. Every later phase consumes the first immutable bytes for that identity.
4. Public-key normalization never reopens the authority-controlled key path.
5. Distinct cached inputs cannot exceed the aggregate transaction byte ceiling.
6. Private-key type checking and signing use the same captured bytes.
7. In-place bundle update fails if the parent chain, input object, or input bytes changed.
8. A new bundle successor is created exclusively and never overwrites an existing path.
9. Partial or orphaned output is not accepted as evidence and does not change a Gap Ledger row.
10. Unsupported secure filesystem APIs fail closed; there is no path-based compatibility fallback.

## Validation sequence

Repository CI must execute:

```bash
python3 tools/validate_repository.py
python3 tools/validate_repository_metadata.py
python3 tools/validate_production_authority.py
python3 -m unittest discover -s services -p 'test_*.py'
python3 -m unittest discover -s adapters -p 'test_*.py'
python3 -m compileall -q services adapters tools
```

The canonical seven-job workflow must then complete on one unchanged head and produce `hepta-source-evidence-<head-sha>`. A passing prior-head artifact does not transfer to a documentation or source successor.

## Reopen conditions

Reopen `HG-0075` when any of the following is observed:

- any cryptographic phase reopens an authority-controlled pathname instead of using pinned bytes;
- an ordinary directory or final file replacement can be accepted under the earlier identity;
- a non-canonical URI spelling creates a second cache or review identity;
- transaction snapshot growth is unbounded;
- signing reuses a mutable private-key pathname after type validation;
- bundle mutation uses an unchecked path write, follows a symbolic link, overwrites an unrelated object, or can expose a partial successor;
- a required hostile test is deleted, skipped without an explicit platform reason, or no longer exercises the security boundary; or
- the exact-head CI packet or independent review no longer binds the live candidate.

## Claim ceiling

The repository may claim only source implementation and E1–E4 test/build evidence for this change. The following remain outside this closure: physical Even G1 qualification, production providers and OAuth, provider-side credential revocation, KMS/HSM and platform attestation, GitHub administrator policy application, vendor firmware authority, independent multidisciplinary assurance, signed binaries, pilot, staged rollout, rollback, store approval, and product release.
