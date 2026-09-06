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

### Signing input, lineage, and bundle publication

Private-key inspection and signing use one descriptor-captured key snapshot. The original key pathname is never reopened for the signing phase.

The input bundle must be located below the same declared custody root that receives the detached signature and bundle successor. This prevents a caller from placing a private key beside the input evidence while declaring a different output root as the only custody boundary. The private key remains outside the complete lineage root.

Authority-bearing bundle operations never rewrite the input bundle. Portable POSIX rename does not provide an atomic expected-inode compare-and-swap, so a check followed by in-place replacement would leave a race against a concurrent name substitution. Every submission signature, reviewer signature, and final digest therefore requires `--output-bundle-uri` and creates one new exclusive mode-0600 successor below the declared custody root. The input remains byte-for-byte unchanged.

Signing commands preflight canonical output URIs before producing a signature. A detached signature and its successor bundle cannot share one URI. After exclusive creation, both signature and successor are re-read from their visible canonical paths; redirection, disappearance, permission weakening, or byte replacement prevents a successful result.

## Implementation map

| Responsibility | Source |
|---|---|
| Validation transaction, URI canonicalization, object identity and aggregate budget | `tools/external_evidence/snapshot_io.py` |
| Snapshot-backed trust normalization | `tools/external_evidence/__init__.py`, `tools/external_evidence/trust.py` |
| Descriptor-bound private key, signatures and immutable bundle output | `tools/external_evidence/signing_io.py` |
| Submission/reviewer/finalize preflight, declared-root binding and output readback | `tools/external_evidence/signing.py`, `tools/sign_external_evidence.py` |
| Validation hostile tests | `services/qualification/test_external_evidence_filesystem_hardening.py` |
| Signing hostile tests | `services/qualification/test_external_evidence_signer_custody.py`, `services/qualification/test_external_evidence_signing_boundaries.py` |

## Required invariants

1. One canonical scoped URI has one lexical cache identity.
2. Every opened ancestor and final input object must match the identity captured before consumption.
3. Every later phase consumes the first immutable bytes for that identity.
4. Public-key normalization never reopens the authority-controlled key path.
5. Distinct cached inputs cannot exceed the aggregate transaction byte ceiling.
6. Private-key type checking and signing use the same captured bytes.
7. The input bundle, artifacts, signatures, and successors share one declared custody root; private keys remain outside it.
8. Signing and finalization reject a missing successor URI and never rewrite the input bundle.
9. Signature and successor bundle URIs are canonical, distinct, exclusive, and private.
10. Every created output is visibly re-read and byte-compared before command success.
11. Partial or orphaned output is not accepted as evidence and does not change a Gap Ledger row.
12. Unsupported secure filesystem APIs fail closed; there is no path-based compatibility fallback.

## Signing sequence

A submission or reviewer signing command must allocate a new successor URI:

```bash
python3 tools/sign_external_evidence.py submission \
  --bundle <custody-root>/unsigned-or-prior.json \
  --custody-root <custody-root> \
  --output-bundle-uri artifact://successors/submission-001.json \
  --index 0 \
  --private-key <private-key-outside-custody.pem> \
  --signature-uri artifact://signatures/submission-001.sig
```

The next operation consumes the verified successor as its input and writes another new successor. Reusing a successor or signature URI fails because creation is exclusive. The two output URIs must differ.

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
- the input bundle is accepted outside the declared custody root or a private key is accepted inside it;
- an authority-bearing command rewrites its input bundle or permits operation without a new exclusive successor URI;
- signature and successor URIs can alias, or a successor write follows a symbolic link or overwrites an existing object;
- a command can report success without re-reading the complete visible output bytes and private mode;
- a required hostile test is deleted, skipped without an explicit platform reason, or no longer exercises the security boundary; or
- the exact-head CI packet or independent review no longer binds the live candidate.

## Claim ceiling

The repository may claim only source implementation and E1–E4 test/build evidence for this change. The following remain outside this closure: physical Even G1 qualification, production providers and OAuth, provider-side credential revocation, KMS/HSM and platform attestation, GitHub administrator policy application, vendor firmware authority, independent multidisciplinary assurance, signed binaries, pilot, staged rollout, rollback, store approval, and product release.
