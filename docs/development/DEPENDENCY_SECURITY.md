# Dependency security and update operations

Status: repository-controlled proposal automation and bounded lockfile maintenance. This document does not assert that an update is safe merely because a bot or operator produced a diff.

## Supported automated ecosystems

Dependabot monitors the exact manifests used by the canonical build for three supported ecosystems:

- GitHub Actions in the repository root;
- Dart and Flutter packages in the repository root;
- Gradle dependencies under `android/`.

The three supported ecosystems run weekly in staggered Asia/Singapore windows with at most five open version-update pull requests per ecosystem. The accepted YAML values are checked against the dated official-value snapshot in `contracts/dependabot-supported-ecosystems-v1.json`.

Dependabot does not support CocoaPods. The `swift` ecosystem value is for Swift Package Manager and is not a substitute for a repository that uses `Podfile` and `Podfile.lock`. The repository therefore makes no false CocoaPods automation claim.

## CocoaPods boundary

The current Pod graph contains no registry-hosted Pod declaration. `Podfile.lock` contains only the local Flutter source, and canonical iOS qualification executes `pod install --deployment`. `tools/refresh_cocoapods_lock.py --check` verifies that boundary without network access.

An authorized operator can refresh the lock on a clean named non-`main` branch with:

```bash
HEPTA_COCOAPODS_UPDATE_APPROVED=1 \
  python3 tools/refresh_cocoapods_lock.py --apply
```

The tool does not commit, push, open, approve or merge a pull request. It refuses a dirty worktree, `main`, a detached head, missing toolchain, external Pod declarations, external sources other than local Flutter, or changes outside `ios/Podfile.lock`. The resulting diff must enter the ordinary exact-head review path.

Introducing any registry-hosted Pod is a new dependency and trust-boundary change. The fail-closed check blocks it until maintainers add an applicable supported update mechanism, provenance/licensing review, vulnerability monitoring and corresponding CI tests.

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

The official ecosystem-value snapshot is evidence about configuration syntax, not permanent authority. When GitHub changes the supported table, update the snapshot and its retrieval date in a separately reviewed source change before using a new YAML value.

## Platform and release requalification

Dependency changes that affect BLE, LC3/RNNoise, Android/iOS SDK behavior, cryptography, identity, model or speech transport require the corresponding integration and physical qualification to be repeated. Repository CI does not substitute for signed mobile binaries, physical Even G1 traces, production provider receipts, KMS/HSM or attestation evidence.

The resulting SBOM is source evidence only. A release additionally needs binary SBOM/provenance bound to the signed distributable and accepted by the release authority.

## Failure and rollback

If an update fails tests, changes behavior, increases permissions, weakens a fail-closed boundary or cannot be independently reviewed, close or revert the proposal. Do not reduce test coverage, relax scanners, add broad version ignores, transfer an earlier Artifact, or alter branch protection to make the update pass.

A rollback is itself a new source object and requires fresh exact-head qualification. Production rollback additionally follows the signed-binary and provider/device rollback runbooks.
