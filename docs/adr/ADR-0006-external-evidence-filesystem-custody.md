# ADR-0006: Pin external-evidence inputs by lexical identity and create signatures without path re-resolution

- Status: accepted for G9 source
- Date: 2026-09-02
- Extends: `ADR-0004-external-evidence-authentication.md`
- Plan revision: `2026-09-02-g9-authenticated-1`

## Context

ADR-0004 makes authority-owned evidence non-self-issuable through an externally pinned Ed25519 trust registry, exact canonical statements, signed issuer attestations, signed acceptance decisions, strict key scope, and independent-review separation. Those cryptographic checks are only meaningful when every validation phase observes the same bytes.

A path string, successful scope check, or SHA-256 comparison does not by itself provide a stable byte identity. On a writable filesystem, a symbolic link or file name can be redirected between path resolution, digest calculation, JSON parsing, secret scanning, public-key inspection, and OpenSSL verification. If each phase resolves the same URI again, one phase can inspect trusted bytes while another consumes attacker-controlled bytes. A similar check-then-write defect exists when a signing helper validates an output path and later calls an ordinary path-based write: an output directory or final file can be replaced by a symbolic link after validation.

The threat model therefore includes a concurrent repository or custody-directory writer who can replace regular files, retarget symbolic links, create dangling links, or race output-directory creation. The operating-system kernel and process are trusted; a hostile kernel, compromised OpenSSL binary, or arbitrary process-memory modification is outside this source contract.

## Decision

### One validation transaction, one byte view

Every supported `validate_bundle` entry point runs inside one `validation_snapshot` transaction. The transaction owns an in-memory map from normalized lexical absolute paths to immutable byte strings. Nested validation calls reuse the same map. The cache is discarded only after the top-level validation completes.

The cache key is the lexical path derived from the scoped URI, not the current resolved target. A symbolic link that later points somewhere else therefore cannot create a second cache identity for the same `artifact://` or `key://` subject.

### Scoped URI selection

`artifact://` and `key://` values must contain bounded relative POSIX paths with no empty, absolute, `.` or `..` components. The lexical path is formed below the resolved custody root. The currently resolved target must also remain below that root; an existing link to an external target fails before any bytes are accepted.

When the scoped path already exists, path selection is the first security-relevant read. The implementation immediately opens the selected resolved target and pins its stable bytes under the lexical cache key. This closes the interval between safe path selection and the first later hash, parse, secret scan, key check, or signature verification.

A non-existing path may be returned only for the signing helper's new detached-signature destination. Validation reads remain strict and require the target to exist.

### Stable bounded input reads

The first input read:

1. resolves the selected lexical path with `strict=True`;
2. opens the resolved target read-only with close-on-exec and no-follow semantics where supported;
3. requires the opened descriptor to reference a regular file;
4. rejects the file before reading when its reported size exceeds the caller's bound;
5. reads through the descriptor in bounded chunks;
6. compares device, inode, size, modification time, and change time before and after the read;
7. requires the accumulated byte count to equal the opened file size; and
8. stores the resulting bytes under the lexical path identity.

Every later read of the same lexical identity returns the pinned bytes. A caller that requests a smaller bound still rechecks that the cached byte length fits the new bound.

This design intentionally authenticates the bytes used by the current validation transaction. It does not claim that a pathname remains immutable after validation, and it does not turn repository custody into external authority.

### Detached-signature output custody

A detached signature is a new object and must never overwrite an existing path. The signing helper:

1. resolves and opens the custody root as a real directory;
2. walks every relative directory component with directory descriptors and `O_DIRECTORY | O_NOFOLLOW`;
3. creates a missing directory relative to its already-open parent with mode `0700`, then reopens it with no-follow semantics;
4. creates the final file relative to the final directory descriptor with `O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW` and mode `0600`;
5. writes the complete signature through the returned descriptor;
6. flushes the file before reporting success;
7. verifies that the resulting descriptor is a regular file with the exact expected byte count; and
8. removes a partially created final entry when any later step fails.

Existing files, dangling final symbolic links, symbolic-link directory components, paths escaping the custody root, unsupported descriptor-relative platforms, short or stalled writes, and non-regular outputs fail closed. The helper returns no success merely because a path-based write call returned.

The signing helper still writes only detached signature bytes. Private keys remain external and are never copied into repository or evidence custody.

## Required negative evidence

The deterministic test suite must prove at least the following:

- replacing one lexical file after its first read does not change later validation bytes;
- retargeting one scoped symbolic link between repeated reads does not change the pinned bytes;
- retargeting a scoped link after path selection but before the first explicit read cannot change the selected input;
- a scoped link that initially resolves outside the custody root is rejected;
- a symbolic-link output directory is rejected and receives no signature;
- an existing or dangling symbolic-link final destination is rejected and its target is not created;
- an existing regular signature is never overwritten; and
- valid new detached signatures remain verifiable under the expected Ed25519 public key.

These tests supplement, rather than replace, the key-substitution, parser-differential, timestamp, review-order, authority-alias, and fabricated-bundle tests required by ADR-0004.

## Alternatives rejected

- **Resolve the path before every phase:** the same lexical URI can expose different targets during one validation.
- **Cache by resolved target:** retargeting a symbolic link creates a new cache key and defeats same-subject immutability.
- **Pin only on the first explicit digest call:** leaves a race between scope validation and first consumption.
- **Use `Path.write_bytes` after checking containment:** re-resolves mutable path components at write time.
- **Permit overwrite for convenience:** destroys evidence provenance and lets a later signer replace an already referenced signature.
- **Trust file size and modification time without descriptor identity:** path replacement can substitute another object with similar metadata.
- **Follow symbolic-link output directories that remain inside the root:** a later retarget still creates a check-then-write boundary.
- **Treat a successful source test as external evidence:** filesystem hardening establishes only repository-controlled source assurance.

## Consequences

External-evidence validation now has a deterministic byte view across hashing, parsing, secret scanning, public-key normalization, and signature verification. Signing output is fail-closed against ordinary path replacement and symbolic-link redirection and produces one immutable new signature entry.

The implementation requires descriptor-relative filesystem APIs and no-follow support for signing. Unsupported platforms fail rather than silently falling back to path-based writes. Evidence operators must choose a new signature URI for a new statement and must not expect the helper to overwrite or repair an existing custody entry.

These controls close a repository-actionable TOCTOU class. They do not close any inherited physical, provider, administrator, vendor, independent-assurance, signing-authority, pilot, store, production, or release gap. Those facts still require externally pinned, cryptographically authenticated evidence from the named real authorities.
