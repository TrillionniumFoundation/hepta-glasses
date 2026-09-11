# ADR-0010: Preserve lexical evidence identity across one validation transaction

- Status: accepted for G10 repair source
- Date: 2026-09-03
- Extends: `ADR-0006-external-evidence-filesystem-custody.md`
- Extends: `ADR-0007-evidence-object-identity-and-bounded-custody.md`
- Extends: `ADR-0009-trusted-verifier-and-contract-content-binding.md`
- Source repair: `HG-0079`

## Context

The G9 snapshot layer opened individual files with no-follow descriptor
semantics, but `safe_scoped_path()` first called `Path.resolve()` on the scope
root and target. A symbolic-link root, parent, or final name could therefore be
converted into a resolved ordinary path before the no-follow reader saw it.

Individual reads also captured directory identity independently. Replacing a
custody root or shared parent between two stable reads could let one validation
transaction assemble bytes from different ordinary-directory generations. The
cryptographic digests still constrained content, but the stated exact-object
custody invariant was stronger: all inputs named under the same lexical tree
must share one stable ancestor lineage for the entire transaction.

## Decision

### Lexical names are authoritative

Artifact and key URIs are parsed as canonical relative POSIX paths and joined
to an absolute lexical scope root without resolving symbolic links. The root,
every target parent, and every final file are inspected and opened with
no-follow semantics. A symlink is rejected even when it points to a regular
file inside the declared root.

Missing final files may be represented only after every existing parent has
been verified as a real directory. Any later authority-bearing read still
requires the final object to exist as a bounded regular file.

### Ancestor identities are transaction-wide

The public validation snapshot now owns a second context: a map from each
absolute lexical directory name to its captured `(device, inode, file-type)`
identity. Every file and scope read compares all shared ancestors with this
map. A rename-and-replace of the custody root, artifact directory, key
directory, or another shared parent between reads fails the transaction.

Directory metadata that does not change object identity is not pinned; adding
unrelated entries does not by itself invalidate a read. Object replacement does.

### Final-name postcondition

After a file descriptor has been read, the validator re-captures the lexical
ancestor and final-file identities. The read succeeds only when:

1. the opened descriptor remained the same bounded regular file;
2. every ancestor remained the same directory object; and
3. the visible final name still identifies the opened file.

Renaming or replacing the final name after open therefore cannot leave a
successful result referring to a different visible object.

### One implementation for every consumer

`lexical_scope_policy.py` is installed immediately after the base snapshot
primitives and before signing, trust, submission, acceptance, or complete
closure modules import core helpers. It replaces:

- `validation_snapshot`;
- `_stable_read_target`;
- `_read_bounded_file`;
- `_safe_scoped_path`;
- `safe_artifact_path`;
- `safe_key_path`; and
- normalized public-key digest input handling.

Consequently bundle, contract, registry, public key, evidence artifact,
signature, review artifact, and signer input reads share the same lexical and
transaction identity rules.

## Required negative evidence

The qualification suite must prove that validation rejects:

- a symbolic-link custody root;
- a symbolic-link parent inside custody;
- a symbolic-link final file, including an in-root alias;
- direct bounded reads through a final symlink;
- custody-root replacement between two reads; and
- shared parent-directory replacement between two reads.

Ordinary lexical files must still validate and return the expected pinned bytes.

## Alternatives rejected

- **Resolve then check containment:** follows the very links the custody policy
  claims to reject.
- **Check only final-file `O_NOFOLLOW`:** intermediate links remain traversable.
- **Capture each read independently:** permits a mixed-generation transaction.
- **Pin directory timestamps:** ordinary unrelated directory updates create
  false failures; object identity is the relevant invariant.
- **Rely only on hashes and signatures:** authenticates content but does not
  satisfy the declared exact visible-object and custody-lineage contract.

## Consequences

Supported authority validation requires operating-system directory-descriptor
and no-follow primitives. Unsupported hosts fail closed. A process with power
to replace root-owned runtime objects remains outside this repository source
boundary and requires host attestation and operational custody.

This repair strengthens repository-controlled validation only. It creates no
physical-device result, provider receipt, administrator readback, firmware
vendor authority, independent assurance, signed product binary, pilot result,
store approval, deployment, or release authorization.
