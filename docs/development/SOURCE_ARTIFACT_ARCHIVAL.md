# Source Artifact archival and long-term revalidation

Status: repository-controlled verification protocol. No archive, receipt, trust registry, or release authority exists merely because this document, its schema, template, verifier, or tests exist.

## Problem and authority boundary

A canonical CI run uploads `hepta-source-evidence-<exact-head>`, but GitHub Actions Artifact retention is finite. Expiry or deletion must fail closed. A copied ZIP is not durable evidence unless an external custodian preserves the exact bytes under a content address and signs a receipt that binds the repository, source commit, source tree, Artifact identity, SHA-256, size, custody identity, key identity, archive time, and retention term.

The repository is an untrusted subject. It supplies the source producer, schema, verifier, and hostile tests, but it cannot appoint its own independent archive authority. The trust registry must resolve outside the checked-out repository and must be administered by a controller independent of the submitting repository writer. The private Ed25519 key never enters GitHub Actions, source control, pull requests, issue comments, developer workstations, or repository fixtures.

## Required packet

A revalidation transaction has four distinct inputs:

1. the exact ZIP downloaded from the successful canonical workflow;
2. a detached-signature receipt conforming to `schemas/source-artifact-archive-receipt.schema.json`;
3. an out-of-band trust registry containing the unique active Ed25519 custodian public key; and
4. an explicit trusted UTC verification time supplied by the verifier operator.

Ambient host time is not silently trusted. `--verification-time` is mandatory, uses whole-second RFC 3339 UTC, and should come from the controlled verifier environment or a witnessed time service. A future-dated receipt, an empty retention interval, or a receipt whose retention has expired at that trusted time is rejected.

## Exact Artifact inventory and ZIP custody

The archive must contain exactly these seven regular files and no directory, duplicate, alias, symlink, special file, encrypted member, unsafe pathname, or alternate compression method:

```text
source-evidence-summary.json
source-gate-result.json
source-history-scan.json
source-native-sanitizer.json
source-provenance.json
source-release-bundle.json
source-sbom.spdx.json
```

The verifier reads the Artifact through one bounded stable file descriptor, hashes those exact bytes, and opens an in-memory copy of the same bytes. It rejects object replacement during the read, oversized archives or members, excessive aggregate expansion, compression-ratio bombs, truncated central directories, CRC failure, absolute paths, backslashes, `.`/`..` components, duplicate names, directories, symlinks, and non-regular entries.

Each JSON member is strict UTF-8 without BOM, duplicate members, non-finite numbers, excessive depth, or excessive node count. The verifier does not trust the outer receipt alone: it independently binds the summary, provenance, history scan, native report, release bundle, source gate, and SPDX 2.3 SBOM to the same repository/head/tree and recomputes every cross-digest.

## Internal evidence requirements

The source gate must be `mode=source`, `passed=true`, have an empty `missing` array, contain the exact canonical check inventory, and report every check true. The release bundle must contain the six predecessor CI jobs in canonical order with `success`, and it must bind the exact history, native, provenance, and SBOM member digests.

The history report must cover all fetched refs and deduplicated blobs, bind the exact head, and contain zero unacknowledged findings, unused acknowledgements, and unscanned blobs. The native report must pass and retain LC3 cross-platform parity. Provenance must identify the canonical builder and exact repository/head/tree, must not be future-dated relative to trusted verification time, and must bind the history, native, and SBOM bytes.

The SPDX document must be SPDX 2.3, identify `TrillionniumFoundation/hepta-glasses@<head>`, use the head-bound namespace, contain the canonical application package, expose unique file and SPDX identities, bind every source file with one lowercase SHA-256, agree with summary counts, and retain all four source ecosystems: Android/Gradle, Dart/pub, iOS/CocoaPods, and native/vendored.

## Signature and trust transaction

The signature covers canonical UTF-8 JSON for every receipt field except `signature`. Object members are sorted, and compact separators are used. The verifier requires the fixed `/usr/bin/openssl` executable rather than an ambient `PATH` replacement. The selected key must be unique, active, Ed25519, valid at `archived_at`, and represented only as a public-key PEM. A revoked, inactive, duplicate, expired-at-signing, private, malformed, repository-contained, or substituted key fails closed.

The receipt's `archive_object` must equal `sha256:<artifact_sha256>`. The supplied Artifact bytes must exactly match both digest and size. Renaming, regenerating, recompressing, adding metadata, or rebuilding semantically equivalent evidence creates different bytes and requires a new receipt.

## Verification

```bash
python3 tools/verify_source_archive_receipt.py \
  --receipt /secure-intake/receipt.json \
  --artifact /secure-intake/hepta-source-evidence-<head>.zip \
  --trust-registry /etc/hepta/archive-trust-registry.json \
  --repository-root "$PWD" \
  --verification-time 2026-09-09T12:00:00Z \
  --expected-head <40-lowercase-hex-head> \
  --expected-tree <40-lowercase-hex-tree>
```

A passing result records the exact object tuple, trusted verification time, member count, source-gate check count, and SBOM counts. Operators should download the GitHub Artifact twice through independent sessions and require byte identity before the custodian accepts it. The custodian stores the immutable ZIP under its content address, signs the receipt with an isolated key, and preserves receipt, object, trust-registry history, access log, and retention policy.

## Failure, renewal, and recovery

Any digest, size, signature, key status, time, repository identity, source identity, member inventory, CRC, internal cross-binding, gate result, history result, sanitizer result, or SBOM invariant mismatch rejects the packet. Do not repair or normalize the received object in place.

Retention renewal or custody transfer requires a newly signed receipt over the same immutable bytes. A new source head, workflow, toolchain, dependency, regenerated Artifact, changed compression, or changed source-evidence member requires a new object and fresh exact-head qualification. If both the GitHub Artifact and the external immutable object are unavailable, revalidation is lost and the gate returns to blocked.

## Claim ceiling

This protocol closes only the repository-controlled archival schema, parser, ZIP-custody, cross-binding, trusted-time, signature-verification, and hostile-test gaps. It does not assert that an external custodian exists, that any current Artifact has been accepted, that a trust registry is independently administered, or that production identity, provider, KMS/HSM, physical Even G1, firmware, independent assurance, signing, pilot, rollback, store, or release evidence exists.
