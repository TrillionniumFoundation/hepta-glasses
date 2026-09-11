# Release version authority and promotion contract

Status: repository-controlled version truth. This document does not assert that a signed binary or production release exists.

## Responsibility and API

`pubspec.yaml` is the sole repository version authority. Its `version` field uses `major.minor.patch+positive_build` with no leading zeroes. Android projects the semantic version and build number through `flutter.versionName` and `flutter.versionCode`. iOS projects them through `FLUTTER_BUILD_NAME` and `FLUTTER_BUILD_NUMBER` in `Info.plist` and the Runner project configuration.

`contracts/release-versioning-v1.json` is the closed machine contract. `tools/validate_release_version.py` validates the authority, projections, changelog, tag syntax, promotion controls, and documentation. No platform file may introduce an independent literal product version.

## State, concurrency, and promotion

A repository version identifies source, not product maturity. Every source, dependency, workflow, contract, toolchain, signing, entitlement, provider, firmware, or hardware-matrix movement creates a new candidate object and invalidates evidence that was bound to its predecessor.

Promotion is never automatic. Source admission requires all seven canonical jobs on one unchanged head, a content-verified exact-head source Artifact, an eligible latest-head non-pusher review, resolved conversations, and ordinary protected adoption. A tag, changelog entry, green subset of jobs, administrator assertion, or copied Artifact cannot promote the candidate.

## Failure and recovery

Malformed versions, zero or non-integer build numbers, duplicate version declarations, platform literals, projection drift, changelog mismatch, an unclosed contract, or an automatic/evidence-transfer promotion flag fail repository validation.

A rollback is a new source object. Reusing an older version, tag, Artifact, signature, provisioning profile, device report, provider receipt, or approval is prohibited unless the governing external authority explicitly issues a new binding for the exact rollback candidate.

## Configuration, migration, and tags

The repository tag shape is `v<major>.<minor>.<patch>+<positive_build>`. Tags are immutable release references after publication. Moving or deleting a release tag is an incident requiring independent investigation; creating a correctly shaped tag does not itself establish signing or distribution.

Changing the Dart package name, Android namespace/application ID, iOS bundle identifier, entitlement application identifier, or store identity requires an explicit atomic migration. Version projection must remain single-source throughout that migration, and upgrade/data compatibility must be tested on signed builds.

## Operations and verification

Run:

```bash
python3 tools/validate_release_version.py
python3 -m unittest services.qualification.test_release_version
```

Dependency proposals and version changes require release-note review, complete manifest/lockfile diff review, exact-head CI, fresh source evidence, and a new eligible review. The release operator records the exact source commit, tree, tag, signed binary digest, binary SBOM/provenance, signer, rollout channel, and rollback target as separate facts.

## Platform and evidence ceiling

Repository validation proves only that Android and iOS consume the same source version and that promotion rules are represented consistently. It does not prove provisioning, signing, installation, upgrade, physical Even G1 compatibility, production provider behavior, pilot success, rollback readiness, store approval, or public release. Those remain E5-E7 authority facts.
