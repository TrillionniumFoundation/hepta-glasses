# G10 lexical validation custody

## Scope

This guide documents the G10 repair that removes resolve-first path handling
from authority-bearing evidence validation. It applies to contracts, bundles,
trust registries, public keys, evidence artifacts, detached signatures, review
artifacts, and signing inputs.

It does not turn repository source or CI into external E5–E7 evidence.

## Invariants

For every scoped URI and direct evidence read:

1. the canonical URI supplies a relative lexical path with no empty, dot, or
   parent component;
2. the scope root is converted only to an absolute lexical name, never to a
   symlink-resolved target;
3. the root and every parent component are real directories opened with
   descriptor-relative no-follow operations;
4. the final object is a bounded regular file opened with `O_NOFOLLOW`;
5. lexical-before, opened, descriptor-after, and lexical-after identities
   agree;
6. the visible final name still identifies the opened object after reading;
7. all shared ancestor directory identities agree across the complete
   validation transaction; and
8. all cached bytes are keyed by the canonical lexical path and counted against
   the aggregate snapshot bound.

A symbolic link is rejected even when it resolves to an otherwise valid object
inside the custody root.

## Component map

| Component | Responsibility |
|---|---|
| `snapshot_io.py` | Base descriptor, identity, byte-snapshot, and aggregate-budget primitives |
| `lexical_scope_policy.py` | Lexical path joining, transaction-wide directory pinning, post-read visible-name checks, and normalized-key input binding |
| `__init__.py` | Installs lexical policy before trust, signing, submission, acceptance, and closure consumers import core helpers |
| `test_external_evidence_lexical_scope_policy.py` | Positive lexical read and hostile root/parent/final-link plus cross-generation replacement tests |
| `repository_admission.py` | Independently performs descriptor-anchored recursive admission of committed accepted packages |

## Validation flow

```text
public validate_bundle
  -> create byte snapshot and directory-identity snapshot
  -> read canonical contract by lexical no-follow path
  -> read bundle by lexical no-follow path
  -> validate and pin trust-registry tree
  -> resolve each artifact/key/signature URI lexically
  -> compare every shared ancestor with the transaction snapshot
  -> open final file no-follow
  -> read bounded bytes
  -> verify descriptor stability
  -> verify ancestor and final visible-name identity after read
  -> cache exact bytes by lexical path
  -> perform digest, Ed25519, authority, quorum, and acceptance checks
```

## Failure semantics

The validator returns no successful partial result when:

- a root, parent, or final component is a symbolic link;
- a root or parent directory is renamed and replaced between reads;
- a final file is renamed or replaced while its descriptor is open;
- an object changes size, timestamps, type, device, or inode during the read;
- a path becomes missing after it was opened;
- a path leaves its canonical lexical scope; or
- the aggregate byte budget is exceeded.

The predecessor byte snapshots and detached signature semantics remain
unchanged. This policy only tightens how filesystem objects are selected and
kept coherent.

## Test procedure

Run the focused suite:

```bash
python3 -m unittest \
  services.qualification.test_external_evidence_lexical_scope_policy \
  services.qualification.test_external_evidence_entrypoint_snapshot \
  services.qualification.test_external_evidence_runtime_policy
```

Then run the complete repository contract suite:

```bash
python3 -m unittest discover -s services -p 'test_*.py'
python3 -m unittest discover -s adapters -p 'test_*.py'
python3 -m compileall -q services adapters tools
```

The final candidate additionally requires every canonical mobile, native,
secret-boundary, and source-evidence CI job on one unchanged exact head.

## Reopen conditions

Reopen the custody repair if any supported validation or signing path can:

- accept a linked root, intermediate directory, or final file;
- resolve a URI before applying no-follow checks;
- observe different generations of one shared directory in one transaction;
- report success after the visible final name no longer identifies the opened
  file; or
- bypass the lexical policy through a public package, direct module,
  compatibility, or CLI entrypoint.

Host compromise, root-owned runtime replacement, physical qualification,
provider control-plane facts, branch-protection administration, external trust
registry issuance, independent review, production signing, pilot operation, and
store approval remain separately owned gates.
