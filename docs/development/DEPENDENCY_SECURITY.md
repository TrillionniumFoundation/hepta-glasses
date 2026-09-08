# Dependency security and update operations

Status: repository-controlled dependency proposal automation, closed-world CocoaPods admission, and an externally operated hermetic lock-refresh contract. This document does not assert that an update is safe merely because a bot or operator produced a diff.

## Supported automated ecosystems

Dependabot monitors the exact manifests used by the canonical build for three supported ecosystems:

- GitHub Actions in the repository root;
- Dart and Flutter packages in the repository root;
- Gradle dependencies under `android/`.

The three supported ecosystems run weekly in staggered Asia/Singapore windows with at most five open version-update pull requests per ecosystem. No dependency pull request is auto-merged, and the configuration grants no target-branch bypass, external registry credentials, or insecure external-code execution.

The complete `.github/dependabot.yml` object is independently bound before any ecosystem value is extracted. `tools/native/dependabot_config_custody.py --check` verifies its exact bytes, SHA-256, size, line count, field order, directories, schedules, proposal limits, prefixes, and prohibited authority tokens. Quoted alternate values, YAML anchors, aliases, merge keys, extra ecosystems, encoding drift, comments used as decoys, and partial regular-expression matches cannot preserve admission credit.

The configured YAML identifiers are not accepted from a repository-authored allowlist alone. `contracts/dependabot-supported-ecosystems-v1.json` pins the `github/docs` repository, a full immutable Git commit, and GitHub's official package-manager table path. The canonical `repository-contracts` job calls `tools/native/dependency_update_policy.py --verify-dependabot-official`, retrieves that exact public GitHub object through a no-redirect API request without credentials, decodes the returned blob, parses the table's YAML values, and rejects any configured identifier absent from the external document. HTTP, redirect, JSON, base64, path, SHA, table-shape, count, or parsing failure closes the check rather than being skipped.

Moving either reviewed object is a new source change. It requires review of the upstream diff, all seven canonical jobs on the new unchanged head, a fresh exact-head source Artifact, and a new eligible review. The workflow never trusts a mutable documentation branch.

Dependabot does not support CocoaPods. The `swift` ecosystem value is for Swift Package Manager and is not a substitute for a repository that uses `Podfile` and `Podfile.lock`. The repository therefore makes no false CocoaPods automation claim.

## CocoaPods closed-world admission

The CocoaPods boundary is closed-world rather than based on a best-effort Ruby regular expression.

`tools/native/dependency_update_policy.py --check-cocoapods` binds the complete reviewed `ios/Podfile` through SHA-256. Any Ruby source, helper call, alias, variable, plugin-installation behavior, source declaration, or target movement fails closed until the Podfile and policy are changed together in an ordinary reviewed pull request. This prevents legal Ruby forms such as parenthesized `pod(...)` calls or helper-driven declarations from bypassing a line-oriented matcher.

The same command parses the complete dependency-bearing `Podfile.lock` surface in a fixed, unique order:

- `PODS`;
- `DEPENDENCIES`;
- `EXTERNAL SOURCES`;
- `SPEC CHECKSUMS`;
- `PODFILE CHECKSUM`;
- `COCOAPODS`.

It rejects missing, duplicate, malformed, reordered, or unexpected sections; duplicate records and fields; invalid encoding, tabs, or trailing whitespace; dependencies or transitive references absent from `PODS`; checksum inventories that differ from Pod roots; sources absent from the resolved graph; unexpected direct or transitive Pods; and origin, version, source-path, Podfile-checksum, spec-checksum, or generator drift. The registry-Pod count is derived from resolved Pod roots not represented by an approved external source; it is not a constant assertion.

The only accepted graph is the current local Flutter Pod:

```text
PODS: Flutter 1.0.0
DEPENDENCIES: Flutter (from `Flutter`)
EXTERNAL SOURCES: Flutter -> :path: Flutter
SPEC CHECKSUMS: Flutter -> reviewed checksum
registry Pod roots: none
COCOAPODS generator: 1.17.0
```

The `COCOAPODS` field is bound to the reviewed CocoaPods `1.17.0` generator. A merely well-formed dotted version is insufficient. Changing the generator requires an explicit source-policy update and fresh qualification.

Canonical iOS lock enforcement is not inferred from an arbitrary substring. The policy binds the complete reviewed `.github/workflows/ci.yml` through its Git blob SHA-1 and structurally requires exactly one unconditional `Install locked CocoaPods dependencies` step under the `ios-native` job, with the exact `cd ios` followed by `pod install --deployment` command. A comment, `echo`, false conditional, unrelated job, duplicate step, or any other workflow drift fails closed.

## External hermetic CocoaPods refresh

The repository never executes CocoaPods, RubyGems, Flutter, Git, shell commands, or another dependency generator from the dependency-policy tool. The former ambient executable refresh path was removed because pathname hash-before/hash-after checks cannot bind the bytes actually executed, the selected Ruby/gem load graph, or a mutable Flutter SDK. A replace–execute–restore race, modified gem payload, or `PATH` substitution could otherwise preserve superficial version and digest checks.

The repository instead emits a machine-readable, non-executing contract:

```bash
python3 tools/native/dependency_update_policy.py \
  --emit-cocoapods-update-contract
```

That contract binds the exact current Podfile, Podfile.lock, canonical workflow, approved CocoaPods version, and allowed repository change set. It explicitly says that the repository executes no generator, Flutter, or Git process. An actual lock refresh must run in an external hermetic environment governed outside the candidate repository. Its independently controlled evidence must include, at minimum:

- immutable environment or image digest;
- Ruby interpreter SHA-256;
- CocoaPods gem-set/load-graph digest;
- Flutter SDK digest;
- network dependency provenance;
- generated lockfile SHA-256;
- invocation transcript digest.

The external environment must produce only `ios/Podfile.lock` as the proposed repository change. The resulting pull request must update the closed-world constants and hostile fixtures whenever the graph, generator, checksums, source, or canonical workflow changes. A repository comment, local shell transcript, mutable container tag, self-issued key, or the old executable path cannot substitute for the external evidence.

This separation is deliberate: repository source can prove what it will accept, but it cannot self-authenticate the toolchain that generated a new dependency graph. Until a real external hermetic refresh packet is supplied, CocoaPods update execution remains an explicit external operational gate rather than a falsely closed repository automation claim.

## Admission policy

Every dependency proposal is an ordinary source change and must preserve the repository's exact-object rules:

1. inspect release notes, provenance, licensing, vulnerability advisories, and transitive changes;
2. resolve the applicable dependency in the approved automation or external hermetic environment rather than hand-editing resolved hashes;
3. review the complete manifest and lockfile diff;
4. run all seven canonical jobs on one unchanged head;
5. independently download and content-verify the exact-head source Artifact twice, including commit/tree, history, native, provenance, and SBOM bindings;
6. obtain an eligible latest-head non-pusher review with all conversations resolved;
7. adopt only through the ordinary protected path without administrator bypass.

A green dependency pull request is not production release evidence. Signing, device, and provider qualification may regress when a compiler, SDK, native library, networking library, speech component, or cryptographic dependency changes.

## Security triage

High or critical advisories are evaluated immediately rather than waiting for the weekly window. The maintainer records the affected package, reachable code path, fixed version, exploitability decision, and any temporary mitigation. Suppression requires a bounded expiry and a named owner; indefinite ignore rules are prohibited.

Updates to GitHub Actions remain pinned by immutable commit SHA in the canonical workflow. A Dependabot proposal may move that SHA, but the review must verify the new action owner, source tag, release provenance, permission surface, and source contents before acceptance.

The official ecosystem pin is syntax evidence, not permanent authority. When GitHub changes support, update the pinned commit only after reviewing the upstream object and confirming the chosen manager actually applies to this repository. Do not add a local string until the live immutable-source check accepts it.

## Platform and release requalification

Dependency changes affecting BLE, LC3/RNNoise, Android/iOS SDK behavior, cryptography, identity, model transport, or speech require the corresponding integration and physical qualification to be repeated. Repository CI does not substitute for signed mobile binaries, physical Even G1 traces, production provider receipts, KMS/HSM, or platform attestation.

The source SBOM is source evidence only. A release additionally needs binary SBOM and provenance bound to the signed distributable and accepted by the release authority.

## Failure and rollback

If an update fails tests, changes behavior, increases permissions, weakens a fail-closed boundary, lacks the required external toolchain evidence, or cannot be independently reviewed, close or revert the proposal. Do not reduce test coverage, relax scanners, add broad version ignores, transfer an earlier Artifact, restore the ambient executable path, or alter branch protection to make the update pass.

A rollback is itself a new source object and requires fresh exact-head qualification. Production rollback additionally follows the signed-binary and provider/device rollback runbooks.
