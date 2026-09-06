# G10 authority-bearing signing transaction custody

## Scope

This guide defines the source-level custody contract for `submission`,
`reviewer`, and `finalize` signing commands. It extends the lexical validation
and immutable-successor controls to the complete signing operation.

It does not create an issuer identity, trust-registry authority, external
attestation, independent acceptance, or product-release permission.

## Threat model

An untrusted local process may attempt to:

- pass a symbolic-link private-key path;
- pass a symbolic-link custody root;
- rename and replace the custody root after the bundle is read;
- replace a shared output parent between detached-signature and successor
  creation;
- redirect one output into a different directory generation;
- make private-key parsing and signing consume different bytes; or
- reuse an existing output name.

The operating-system kernel, root-owned runtime, verified OpenSSL executable,
and the real authority's private-key custody remain trusted operational inputs.

## Transaction state machine

```text
sign_submission / sign_reviewer / finalize
  -> enter one validation_snapshot + directory-identity snapshot
  -> lexically open the input bundle no-follow and pin every ancestor
  -> lexically validate the declared custody root
  -> require the bundle's pinned ancestor prefix to contain that exact root
  -> lexically read the private key outside custody, no-follow, once
  -> verify Ed25519 type and sign from the same private byte snapshot
  -> create detached signature with O_EXCL/O_NOFOLLOW and mode 0600
  -> pin every created or existing output-parent directory
  -> create immutable successor with O_EXCL/O_NOFOLLOW and mode 0600
  -> re-read each visible output and compare exact bytes
  -> require all shared ancestor identities to remain unchanged
  -> report success
```

Any exception reports command failure. An output produced before a later
failure is unreferenced and non-authoritative; the predecessor bundle remains
unchanged.

## Installation

`tools/external_evidence/__init__.py` installs policies in this order:

1. bounded byte snapshots;
2. lexical no-follow path and directory-generation snapshots;
3. absolute trusted OpenSSL and sanitized subprocess environment;
4. low-level signing I/O custody;
5. semantic signature binding and complete-closure validation; and
6. high-level signing-command snapshot wrappers.

The high-level `signing` module is imported only after low-level functions have
been patched, so compatibility imports receive the same implementation.

## Private-key rules

- The supplied key path is converted to an absolute lexical name, not resolved.
- Every parent and the final key are opened no-follow.
- A symbolic-link key is rejected even when it points outside evidence custody.
- A key lexically below the custody root is rejected.
- One bounded byte snapshot is used for key-type verification and signing.
- The key must parse as actual Ed25519 private material.
- No private key is copied into an evidence package, log, issue, PR, or artifact.

## Output rules

- The custody root must be a real lexical directory.
- Output URIs are canonical relative `artifact://` paths.
- Existing parents are opened no-follow; missing parents are created mode 0700.
- Every parent descriptor identity is compared with its lexical identity and
  pinned for the rest of the transaction.
- Final outputs use exclusive creation and mode 0600.
- Detached-signature and successor URIs must differ.
- No overwrite, in-place authority mutation, symlink redirection, or
  cross-generation output is accepted.
- File and parent directories are synchronized before success.

## Hostile tests

`test_external_evidence_signing_transaction.py` proves:

1. symbolic-link private keys fail;
2. symbolic-link custody roots fail without creating output;
3. custody-root replacement fails before output;
4. existing output-parent replacement fails before output;
5. signature and successor cannot span two generations of the same parent; and
6. all three high-level authority operations are snapshot-wrapped.

The inherited signing-boundary, signer-custody, runtime, lexical-scope,
contract-binding, quorum, review-set, and repository-admission suites remain
mandatory.

## Reopen conditions

Reopen this source closure if any supported signing path can:

- follow a private-key or custody symlink;
- read a bundle under one custody-root object and publish under another;
- publish detached signature and successor under different generations of a
  shared parent;
- verify key type from bytes different from those signed;
- overwrite an existing authority object;
- mutate the predecessor bundle in place; or
- bypass the high-level transaction wrapper through a compatibility import.
