# Dependency security and update operations

Status: repository-controlled proposal automation and bounded lockfile maintenance. This document does not assert that an update is safe merely because a bot or operator produced a diff.

## Supported automated ecosystems

Dependabot monitors the exact manifests used by the canonical build for three supported ecosystems:

- GitHub Actions in the repository root;
- Dart and Flutter packages in the repository root;
- Gradle dependencies under `android/`.

The three supported ecosystems run weekly in staggered Asia/Singapore windows with at most five open version-update pull requests per ecosystem.

The YAML identifiers are not accepted from a repository-authored allowlist alone. `contracts/dependabot-supported-ecosystems-v1.json` pins the `github/docs` repository, a full immutable Git commit, and GitHub's official package-manager table path. The canonical `repository-contracts` job calls `tools/native/dependency_update_policy.py --verify-dependabot-official`, retrieves that exact public GitHub object through a no-redirect API request, decodes the returned blob, parses the table's YAML values, and rejects any configured identifier absent from the external document. HTTP, redirect, JSON, base64, path, SHA, table-shape, count, or parsing failure is closed rather than skipped.

The pin is intentionally reviewable and immutable. Moving it is a new source change that requires review of the upstream diff, fresh seven-job qualification and a new exact-head Artifact; the workflow never trusts a mutable documentation branch.

Dependabot does not support CocoaPods. The `swift` ecosystem value is for Swift Package Manager and is not a substitute for a repository that uses `Podfile` and `Podfile.lock`. The repository therefore makes no false CocoaPods automation claim.

## CocoaPods boundary

The CocoaPods boundary is closed-world rather than based on a best-effort Ruby regular expression.

`tools/native/dependency_update_policy.py --check-cocoapods` first binds the complete reviewed `ios/Podfile` through a SHA-256 constant. Any change to Ruby source, helper calls, aliases, variables, plugin-installation behavior, source declarations or targets fails closed until the Podfile and policy are changed together in an ordinary reviewed pull request. This prevents legal Ruby forms such as parenthesized `pod(...)` calls or helper-driven declarations from bypassing a line-oriented matcher.

The same command parses the complete dependency-bearing `Podfile.lock` surface in a fixed, unique order:

- `PODS`;
- `DEPENDENCIES`;
- `EXTERNAL SOURCES`;
- `SPEC CHECKSUMS`;
- `PODFILE CHECKSUM`;
- `COCOAPODS`.

It rejects missing, duplicate, malformed, reordered or unexpected sections; duplicate records and fields; tabs and trailing whitespace; dependencies or transitive references absent from `PODS`; checksum inventories that differ from Pod roots; sources absent from the resolved graph; unexpected direct or transitive Pods; origin, version, source-path, Podfile-checksum or spec-checksum drift. The registry-Pod count is derived from resolved Pod roots that are not represented by an approved external source; it is not a constant assertion.

The only accepted graph is the current local Flutter Pod:

```text
PODS: Flutter 1.0.0
DEPENDENCIES: Flutter (from `Flutter`)
EXTERNAL SOURCES: Flutter -> :path: Flutter
SPEC CHECKSUMS: Flutter -> reviewed checksum
registry Pod roots: none
```

Canonical iOS qualification independently executes `pod install --deployment`. That command is defense in depth; it does not replace the closed-world source and complete-lock checks.

An authorized operator can refresh the lock on a clean named non-`main` branch with:

```bash
HEPTA_COCOAPODS_UPDATE_APPROVED=1 \
  python3 tools/native/dependency_update_policy.py --refresh-cocoapods
```

The tool does not commit, push, open, approve or merge a pull request. It refuses a dirty worktree, `main`, a detached head, a missing toolchain, an unreviewed Podfile, an unapproved direct/transitive/source/checksum graph, or any tracked or untracked change outside `ios/Podfile.lock`. The resulting diff must enter the ordinary exact-head review path.

An interrupted or rejected refresh may leave a dirty local review branch for inspection. It cannot publish that state. If a legitimate Flutter or CocoaPods refresh changes a reviewed version or checksum, the policy constants and tests must be updated in the same pull request after provenance, licensing and vulnerability review.

Introducing any registry-hosted Pod is a new dependency and trust-boundary change. The fail-closed check blocks it until maintainers add an applicable supported update mechanism, provenance and licensing review, vulnerability monitoring, a deliberately expanded approved graph and corresponding hostile CI tests.

## Admission policy

No dependency pull request is auto-merged. Every update is an ordinary source change and must preserve the repository’s exact-object rules:

1. inspect release notes, provenance, licensing, vulnerability advisories and transitive changes;
2. update the applicable lockfile through the ecosystem's normal resolver rather than hand-editing resolved hashes;
3. run all seven canonical jobs on one unchanged head;
4. independently verify the exact-head source Artifact and its commit/tree, history, native, provenance and SBOM bindings;
5. obtain an eligible latest-head review with all conversations resolved;
6. adopt through the ordinary protected path without administrator bypass.

A green dependency PR is not production release evidence. Signing, device and provider qualification may regress when a compiler, SDK, native library, networking library, speech component or cryptographic dependency changes.

## Security triage

High or critical advisories are evaluated immediately rather than waiting for the weekly window. The maintainer records the affected package, reachable code path, fixed version, exploitability decision and any temporary mitigation. Suppression requires a bounded expiry and a named owner; indefinite ignore rules are prohibited.

Updates to GitHub Actions remain pinned by immutable commit SHA in the canonical workflow. A Dependabot proposal may move that SHA, but the review must verify the new action owner, source tag and release provenance before acceptance.

The official ecosystem pin is syntax evidence, not permanent authority. When GitHub changes support, update the pinned commit after reviewing the upstream object and confirming the chosen manager applies to this repository. Do not merely add a local string until the live immutable-source check accepts it.

## Platform and release requalification

Dependency changes that affect BLE, LC3/RNNoise, Android/iOS SDK behavior, cryptography, identity, model or speech transport require the corresponding integration and physical qualification to be repeated. Repository CI does not substitute for signed mobile binaries, physical Even G1 traces, production provider receipts, KMS/HSM or attestation evidence.

The resulting SBOM is source evidence only. A release additionally needs binary SBOM/provenance bound to the signed distributable and accepted by the release authority.

## Failure and rollback

If an update fails tests, changes behavior, increases permissions, weakens a fail-closed boundary or cannot be independently reviewed, close or revert the proposal. Do not reduce test coverage, relax scanners, add broad version ignores, transfer an earlier Artifact, or alter branch protection to make the update pass.

A rollback is itself a new source object and requires fresh exact-head qualification. Production rollback additionally follows the signed-binary and provider/device rollback runbooks.
