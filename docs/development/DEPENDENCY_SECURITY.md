# Dependency security and update operations

Status: repository-controlled update automation and review policy. This document does not assert that a dependency update is safe merely because a bot opened it.

## Covered ecosystems

Dependabot monitors the exact manifests already used by the canonical build:

- GitHub Actions in the repository root;
- Dart and Flutter packages in the repository root;
- Gradle dependencies under `android/`;
- CocoaPods dependencies under `ios/`.

The four ecosystems run weekly in staggered Asia/Singapore windows with at most five open update pull requests per ecosystem. The configuration neither grants write credentials to build jobs nor creates a second workflow authority.

## Admission policy

No dependency pull request is auto-merged. Every update is an ordinary source change and must preserve the repository’s exact-object rules:

1. inspect release notes, provenance, licensing, vulnerability advisories and transitive changes;
2. update the applicable lockfile through the ecosystem’s normal resolver rather than hand-editing resolved hashes;
3. run all seven canonical jobs on one unchanged head;
4. independently verify the exact-head source Artifact and its commit/tree, history, native, provenance and SBOM bindings;
5. obtain an eligible latest-head review with all conversations resolved;
6. adopt through the ordinary protected path without administrator bypass.

A green dependency PR is not production release evidence. Signing, device and provider qualification may regress when a compiler, SDK, native library, networking library, speech component or cryptographic dependency changes.

## Security triage

High or critical advisories are evaluated immediately rather than waiting for the weekly window. The maintainer records the affected package, reachable code path, fixed version, exploitability decision and any temporary mitigation. Suppression requires a bounded expiry and a named owner; indefinite ignore rules are prohibited.

Updates to GitHub Actions remain pinned by immutable commit SHA in the canonical workflow. A Dependabot proposal may move that SHA, but the review must verify the new action owner, source tag and release provenance before acceptance.

## Platform and release requalification

Dependency changes that affect BLE, LC3/RNNoise, Android/iOS SDK behavior, cryptography, identity, model or speech transport require the corresponding integration and physical qualification to be repeated. Repository CI does not substitute for signed mobile binaries, physical Even G1 traces, production provider receipts, KMS/HSM or attestation evidence.

The resulting SBOM is source evidence only. A release additionally needs binary SBOM/provenance bound to the signed distributable and accepted by the release authority.

## Failure and rollback

If an update fails tests, changes behavior, increases permissions, weakens a fail-closed boundary or cannot be independently reviewed, close or revert the proposal. Do not reduce test coverage, relax scanners, add broad version ignores, transfer an earlier Artifact, or alter branch protection to make the update pass.

A rollback is itself a new source object and requires fresh exact-head qualification. Production rollback additionally follows the signed-binary and provider/device rollback runbooks.
