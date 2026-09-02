# ADR-0007: Bind evidence custody to exact filesystem objects and bounded transactions

- Status: accepted for G9 source candidate
- Date: 2026-09-02
- Extends: `ADR-0004-external-evidence-authentication.md`, `ADR-0006-external-evidence-filesystem-custody.md`
- Plan revision: `2026-09-02-g9-authenticated-1`

## Context

ADR-0006 rejects symbolic-link redirection, pins repeated reads by normalized lexical path, and creates detached signatures with descriptor-relative exclusive creation. Further hostile analysis identified four remaining repository-actionable gaps.

First, `O_NOFOLLOW` rejects a symbolic link at the component being opened, but it does not prove that an ordinary directory reached through the same name is the directory selected during the earlier scope check. An attacker can rename an in-scope directory and replace it with another ordinary directory before the descriptor walk. A no-follow walk can then open the replacement without encountering a symbolic link.

Second, public-key byte hashing and key-type verification used the pinned byte snapshot, while normalized SubjectPublicKeyInfo hashing handed the public-key pathname to OpenSSL again. A key pathname could therefore expose one key for byte hashing and another key for SPKI normalization.

Third, each input had a per-file byte bound but the transaction had no aggregate snapshot-memory ceiling. A syntactically valid bundle containing many maximum-sized artifacts could make the validator retain an excessive amount of memory.

Fourth, the signing helper validated keys and bundles and then reused mutable pathnames for signing or bundle rewrite. That created replacement windows for the private key and for the bundle object that receives signed metadata.

## Decision

### Exact object identity for validation reads

Before an existing input is consumed, the validator captures:

- for every absolute ancestor directory: device, inode, and object type;
- for the final regular file: device, inode, object type, size, modification time, and change time.

The implementation then traverses again from the filesystem anchor with directory descriptors and `O_DIRECTORY | O_NOFOLLOW`. Every opened ancestor must match the captured directory identity, and the final opened regular file must match the captured file identity. A symbolic-link substitution, an ordinary-directory replacement, or a same-name regular-file replacement therefore fails closed rather than selecting a different object.

The opened file is read through its descriptor under the existing byte bound. Its complete identity is checked again after the read. The resulting bytes are cached under the canonical normalized lexical path for the remainder of the top-level validation transaction.

This source contract trusts the kernel and local process. It does not claim protection against a hostile kernel, arbitrary process-memory modification, or storage that violates normal descriptor and inode semantics.

### Canonical URI spelling

`artifact://` and `key://` paths must be canonical POSIX relative paths. Empty components, repeated separators, trailing separators, `.` components, `..` components, and absolute paths are rejected before filesystem access. Semantically equivalent alternate spellings cannot create multiple cache identities or divergent review subjects.

### Aggregate validation budget

The top-level validation transaction tracks the total number of distinct bytes retained in its immutable snapshot. The source default is 512 MiB, below the sum of all theoretical per-file maxima. Exceeding the aggregate ceiling fails closed before another snapshot is admitted. Nested validation calls share the same cache and accounting context.

The aggregate ceiling is a source safety bound, not a recommended evidence-package size. Operational packages should remain substantially smaller and should use separately authenticated manifests for very large raw datasets.

### Snapshot-backed public-key normalization

PEM byte hashing, Ed25519 key-type verification, signature verification, and DER SubjectPublicKeyInfo normalization all consume the same pinned public-key bytes. When OpenSSL requires a pathname, the validator writes those pinned bytes to a private mode-0600 temporary file and normalizes that copy. It never reopens the authority-controlled public-key pathname for the SPKI phase.

### Private-key signing custody

The signing helper reads the private key once through a stable bounded descriptor and copies the captured bytes to a private temporary file. Both key-type inspection and the Ed25519 signing operation use that same temporary snapshot. Replacing or retargeting the original private-key path after the first read cannot change the signing key.

Private-key bytes remain outside repository and evidence custody. The temporary copy is process-local, mode 0600, and deleted with its temporary directory.

### Exact-object bundle update and immutable successor mode

The helper snapshots the input bundle bytes and exact ancestor/file identities before preparing a signature or digest update.

For backwards-compatible in-place operation, it:

1. reopens the exact captured parent-directory chain and input file and verifies every identity;
2. verifies that the current bytes still match the captured input digest;
3. writes the complete successor bytes to one exclusive mode-0600 staging file in the already opened parent;
4. flushes the staging file;
5. rechecks the visible input name against the captured file identity;
6. atomically replaces that exact name through descriptor-relative rename semantics;
7. flushes the parent directory; and
8. verifies that the visible successor has the expected bytes.

The helper also accepts `--output-bundle-uri`. In this mode it creates an exclusive immutable successor below the custody root and leaves the input bundle byte-for-byte unchanged. This mode is preferred for externally reviewed evidence because the unsigned input and signed successor remain independently addressable.

A detached signature is still written before the bundle successor is committed. If the later bundle commit fails, no bundle success is reported; an unreferenced signature object may remain and may be garbage-collected only by an operator that verifies its path and digest. The helper never represents such an orphan as accepted evidence.

## Required hostile tests

The deterministic test suite must prove at least:

- a selected directory replaced by a different ordinary directory is rejected;
- a selected regular file replaced under the same name is rejected;
- repeated separators, trailing separators, `.` and `..` URI aliases are rejected;
- cumulative snapshots above the aggregate transaction ceiling are rejected;
- public-key retargeting cannot change the SPKI digest used for key-alias detection;
- private-key replacement after initial capture cannot change the key that signs;
- a symbolic-link bundle input is not rewritten;
- parent-directory replacement before bundle commit is rejected without changing either object;
- in-place bundle update produces one complete mode-0600 successor through atomic replacement; and
- immutable successor mode leaves the input unchanged and rejects symbolic-link output parents.

## Consequences

G9 evidence I/O is now bound to the filesystem objects selected for the operation rather than merely to path spelling and no-follow traversal. Every cryptographic phase uses one byte snapshot, retained memory is bounded across the transaction, and signing can preserve immutable bundle lineage.

These controls close only a repository-actionable custody class. They do not authenticate an evidence issuer, create a production tenant, operate a physical device, apply GitHub administration settings, provide vendor firmware authority, constitute independent assurance, sign a mobile release, conduct a pilot, or obtain store approval. Those inherited gaps remain blocked until their real authorities issue and independently accept evidence under the externally pinned registry.
