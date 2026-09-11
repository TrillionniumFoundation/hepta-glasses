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

Fourth, the signing helper validated keys and bundles and then reused mutable pathnames for signing or bundle rewrite. Private-key reuse created a substitution window. A path check followed by an ordinary in-place replacement also could not provide a portable atomic compare-and-swap against the expected input inode: another actor could change the visible name between the final check and `rename`/`replace`.

A later review identified two lineage ambiguities that also had to fail closed. The signer accepted an input bundle outside the declared output custody root, which allowed the private-key exclusion boundary and the bundle lineage boundary to name different directory trees. It also relied solely on the descriptor used to create an output and did not re-read the visible canonical URI before returning command success.

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

The input bundle must be located below the same declared `--custody-root` that receives its detached signature and immutable successor. This makes the private-key exclusion boundary, input lineage, and output lineage one explicit tree. A caller cannot move only the output to another root and thereby treat a private key colocated with the input bundle as being outside evidence custody.

Private-key bytes remain outside repository and evidence custody. The temporary copy is process-local, mode 0600, and deleted with its temporary directory.

### Immutable bundle successors are mandatory

The helper snapshots the input bundle bytes and exact ancestor/file identities before preparing a signature or digest update. The input object is never rewritten by an authority-bearing signing or finalization command.

Every successful command requires both `--custody-root` and a fresh canonical `--output-bundle-uri`. For signing commands, the detached-signature URI and successor URI must be distinct. The successor is created below the already selected custody root through descriptor-relative directory traversal, no-follow semantics, and exclusive creation as one mode-0600 regular file. Existing names, dangling links, symbolic-link parents, scope escapes, partial writes, and unsupported secure filesystem operations fail closed. The unsigned input and each signed successor therefore remain independently addressable and content-verifiable.

Before reporting success, the helper resolves neither aliases nor alternate roots: it reopens the exact returned lexical path, requires it still to be a private regular file below the resolved custody root, and compares all bytes with the object just created. The same final readback applies to detached signatures. A disappeared, redirected, permission-weakened, or byte-replaced output cannot produce a successful command result. Later mutation remains detectable by the ordinary evidence validator and does not retroactively create authority.

In-place bundle mutation is deliberately unsupported. Portable POSIX `rename`/`replace` does not offer an atomic “replace this name only when it still references the expected inode” primitive. A stat/open verification followed by rename leaves a final check-to-replacement race. Treating that sequence as an exact-object compare-and-swap would overstate the source guarantee and could overwrite a name changed by another actor.

A detached signature is written before the immutable bundle successor is committed. If the later successor creation fails, no bundle success is reported; an unreferenced signature object may remain and may be garbage-collected only by an operator that verifies its path and digest. The helper never represents such an orphan as accepted evidence.

## Required hostile tests

The deterministic test suite must prove at least:

- a selected directory replaced by a different ordinary directory is rejected;
- a selected regular file replaced under the same name is rejected;
- repeated separators, trailing separators, `.` and `..` URI aliases are rejected;
- cumulative snapshots above the aggregate transaction ceiling are rejected;
- public-key retargeting cannot change the SPKI digest used for key-alias detection;
- private-key replacement after initial capture cannot change the key that signs;
- a private key below the declared custody root is rejected;
- an input bundle outside the declared custody root is rejected before output creation;
- a symbolic-link bundle input is not accepted;
- signing and finalization without a new output-bundle URI fail without changing the input;
- signature and bundle successor URIs cannot alias the same canonical path;
- immutable successor mode leaves the input byte-for-byte unchanged;
- a successor is mode 0600 and cannot overwrite an existing name;
- visible output replacement is detected before command success; and
- symbolic-link output parents or endpoints receive no bundle output.

## Alternatives rejected

- **Path-check then in-place atomic rename:** atomic publication is not an atomic expected-inode comparison; a concurrent name replacement can occur after the check.
- **Best-effort post-rename detection:** detection after publication cannot undo an unintended overwrite or restore a displaced object reliably.
- **Separate input and output custody roots:** this makes private-key exclusion and evidence lineage ambiguous and permits authority-bearing state to cross an undeclared boundary.
- **Trusting only the creation descriptor:** it proves which object was written, but not that the returned canonical URI still exposes that object when success is reported.
- **File locking alone:** advisory locks do not constrain an uncooperative custody writer and do not bind a pathname to an expected inode.
- **Platform-specific conditional rename without a fail-closed portability contract:** evidence tooling must not silently provide weaker guarantees on another supported host.

## Consequences

G9 evidence I/O is bound to the filesystem objects selected for each read rather than merely to path spelling and no-follow traversal. Every cryptographic phase uses one byte snapshot, retained memory is bounded across the transaction, and every authority-bearing signing step advances an immutable bundle lineage instead of mutating prior evidence.

Operators must keep the input bundle, signatures, artifacts, and successors below one declared custody root while keeping every private key outside it. They must allocate a new bundle URI for each submission signature, reviewer signature, or final digest. A successor URI is single-use. Recovery starts from the last independently verified predecessor and ignores unreferenced output objects.

These controls close only a repository-actionable custody class. They do not authenticate an evidence issuer, create a production tenant, operate a physical device, apply GitHub administration settings, provide vendor firmware authority, constitute independent assurance, sign a mobile release, conduct a pilot, or obtain store approval. Those inherited gaps remain blocked until their real authorities issue and independently accept evidence under the externally pinned registry.
