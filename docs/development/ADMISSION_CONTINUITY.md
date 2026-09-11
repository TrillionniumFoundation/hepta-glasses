# Committed external-evidence admission continuity

Status: **CLOSED_SOURCE** for HG-0092. The discovery-to-validation replacement
is implemented and exercised by the repository test lane. This status is not an
exact-head E4, independent-review, product-evidence, deployment or release claim.
HG-0087 and all administrative/external gates remain unchanged. Final source
acceptance still requires an unchanged seven-lane CI run, content-verified source
artifact and an eligible independent latest-head decision.

## Responsibility and entrypoint

`tools/external_evidence/committed_snapshot.py:validate_committed_packages` is the
canonical repository gate. Both committed-package repository tests call this
entrypoint. The older discovery helpers remain diagnostic/negative-test surfaces,
not alternate authorization gates. Direct product bundle validation remains a
separate trusted entrypoint and must still bind exact product source identity and
an externally pinned registry.

The function accepts the repository evidence root and an externally obtained
trust-registry SHA-256. It does not accept a custom validator, clock, executable,
key or override. It calls the existing `tools.external_evidence.validate_bundle`
with complete/accepted flags, captured candidate commit/tree and external pin.
All G10 signature, quorum, contract-binding and independent-review rules remain.

## Problem and design

The previous discovery returned a pathname, parsed envelope and digest after
closing descriptors. The later gate reopened bundle, custody, registry and
artifact names without binding the discovered object to those reads. Stable
individual reads were not a continuous transaction.

The closed source path is:

```text
original no-follow descriptor tree
 -> bounded capture of every file and directory identity
 -> private read-only byte-for-byte copy
 -> accepted-envelope discovery from captured bytes
 -> custody selection from captured names
 -> existing G10 validator reads ONLY private copy paths
 -> verify private copy and original byte/object identities again
 -> return gate result
```

The capture includes envelope, registry, keys, signatures, reviews, artifacts and
ordinary files under the evidence root. It uses canonical relative names, rejects
links and special objects, captures every root ancestor without following links,
and checks opened/final-visible object identity. File opening uses `O_NONBLOCK`
to avoid a regular-file-to-FIFO replacement hanging the verifier. Directory
entry bounds are enforced during enumeration before collecting an unbounded list.

The copy lives in a fresh process-private temporary directory. Files are mode
`0400` and directories are `0500` during validation. Source directories are never
chmod'ed. Discovery and every authority read operate on this one copy. Replacing
an original path cannot substitute new bytes into the validator. Source
replacement, late package addition, permission/inode/content drift or private-copy
modification prevents a successful context return.

The trusted verifier process, operating system, temporary-directory owner,
installed cryptographic runtime and external trust pin remain trusted boundaries.
This does not defend against a hostile kernel or an attacker controlling the
verifier process. Read-only mode is defense in depth; signature verification and
pre/post byte/object checks remain mandatory.

## State, failures and bounds

There is no mutable acceptance state written by this module. A successful report
is returned only after validation and both postconditions complete. A parsing,
path, size, identity, pin or cryptographic error aborts the gate; it is not a
reason to skip the package. Ordinary non-envelope artifacts are not interpreted
as acceptance claims. A repository with no accepted envelopes reports an empty
package set, not that any external gap is closed.

Per-file bound: 16 MiB. Total captured bytes: 256 MiB. Entry count: 100,000.
Directory depth: 64. Bounds are conservative source limits, not an external
provider capacity claim. Captured original bytes, private verification capture
and a postcondition scan can coexist; operators must provision for bounded peak
memory and private temporary disk. Keep this gate off the interactive mobile path.

Every retry starts a new capture; discovery from one attempt is never combined
with validation from another. Any original mutation during an attempt fails
closed. A trusted verifier exception also returns no acceptance. Temporary
storage is removed after use; cleanup never changes original authority files.

## Configuration, compatibility and operations

The caller supplies `HEPTA_EXTERNAL_TRUST_REGISTRY_SHA256` from protected
out-of-band configuration. It cannot be copied from the submitted package as its
own authority. A missing pin fails whenever accepted envelopes exist. The
canonical wrapper retains the existing signed candidate identity for historical
accepted packages; it does not certify them against the latest code automatically.

The envelope/signature schema and contract revision are unchanged: this is a
custody implementation repair, not a weakening or expansion of signed claims.
No production private key or signature is created. Existing valid packages are
verified by the same G10 entrypoint. Rollback to the prior mutable-path gate would
reopen HG-0092 and is not an approved security downgrade.

Run the ordinary repository service lane and the targeted suites:

```bash
python3 -m unittest services.qualification.test_committed_snapshot -v
python3 -m unittest services.qualification.test_committed_snapshot_signed -v
python3 -m unittest services.qualification.test_external_evidence_repository services.qualification.test_external_evidence_repository_admission -v
```

If validation fails, stop admission, preserve the redacted error and investigate
source churn or trust/crypto failures. Do not increase bounds, remove a package,
change its accepted flag or disable negative tests merely to obtain a pass.

## Verification and evidence ceiling

Seventeen isolated source tests cover exact copy/permissions, pin and candidate
binding, strict validation flags, bundle/registry/artifact/key replacement at the
validation boundary, whole-custody replacement, late package addition, private
copy mutation, pre-validation source mutation, missing prerequisites, incomplete
verdicts, linked root/parent/leaf, FIFO race, resource bounds and malformed JSON.
Their mocked verdicts test custody wiring only, not cryptography or real evidence.

The separate integration suite uses cryptographically signed G10 test fixtures
and the private deterministic test clock. It checks real verification of the
copied complete package, registry-pin tampering, and refusal to return success
when the original changes after successful cryptographic validation. Those
fixtures are synthetic source tests, never E5-E7 submissions.

`CLOSED_SOURCE` means the implementation and executable regressions exist. A
successful repository-contracts lane demonstrates those tests on one commit, but
only the final unchanged seven-lane run plus its content-addressed artifact can
supply E4. Independent approval and protected-main adoption remain under HG-0089,
HG-0017 and HG-0044; the implementing identity does not approve its own change.
