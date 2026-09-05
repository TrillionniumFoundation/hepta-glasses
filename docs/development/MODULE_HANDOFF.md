# Module engineering handoff index

Status: active source-candidate supplement. The flattened registry is
`docs/MODULE_COVERAGE.json`; this index selects the primary detailed development
document for every one of its 26 modules. The machine mapping is
`docs/MODULE_HANDOFF.json`, and `tools/validate_module_handoff.py` verifies exact
identity/order, lifecycle, declared dimension profiles, source/test/contract
references, anchors, minimum document length and exact index/status agreement.
These are structural checks, not a proof that every engineering dimension is
semantically complete or current with all code. Module-owner review is required.

The primary documents remain authoritative; this file deliberately does not
duplicate their protocol, state-machine or security text. Source documentation
never promotes a reference implementation, simulator or CI result into physical,
deployed, independent-review or release evidence.

For identity, realtime and capability persistence, the primary documents below
supersede the corresponding reference-only descriptions in the base guide.
The reference modules still exist; a persistent subcomponent does not upgrade
its entire module or close HG-0087. Current remaining work is tracked in
`docs/HG0087_IMPLEMENTATION_STATUS.json`.

<!-- handoff:mobile-shell -->
## mobile-shell

Primary detailed document: `docs/MODULE_DEVELOPMENT_GUIDE.md#mobile-shell`. Platform status: Flutter mobile shell targets Android and iOS. Desktop/web directories are build scaffolding, not qualified product surfaces. Evidence ceiling: Source tests establish startup and presentation behavior only; signing, accessibility/device matrices, store packaging and production rollout require external evidence.

<!-- handoff:edge-runtime -->
## edge-runtime

Primary detailed document: `docs/MODULE_DEVELOPMENT_GUIDE.md#edge-runtime`. Platform status: Runs in the Flutter edge process on both mobile platforms; physical effects are delegated to platform adapters. Evidence ceiling: Deterministic E1–E3 behavior is covered; production identity, physical-effect qualification and crash recovery on signed builds remain external.

<!-- handoff:policy-tool-gateway -->
## policy-tool-gateway

Primary detailed document: `docs/MODULE_DEVELOPMENT_GUIDE.md#policy-tool-gateway`. Platform status: Platform-neutral Dart policy with native effects reached only through typed adapters. Evidence ceiling: The source proves admission semantics; production issuer, attestation, biometric proof and authoritative external reconcilers are not manufactured here.

<!-- handoff:audit-journal -->
## audit-journal

Primary detailed document: `docs/MODULE_DEVELOPMENT_GUIDE.md#audit-journal`. Platform status: Dart journal with Android Keystore and iOS Keychain/CryptoKit checkpoint authentication. Evidence ceiling: Local integrity is source-qualified; retention governance, trusted monotonic or remote roots, backup and incident evidence remain deployment concerns.

<!-- handoff:g1-transport -->
## g1-transport

Primary detailed document: `docs/MODULE_DEVELOPMENT_GUIDE.md#g1-transport`. Platform status: Android and iOS implementations retain separate callback models but the same public authority identity. Evidence ceiling: Hostile source tests do not prove RF behavior, physical protocol compatibility, latency, power, thermal, soak or vendor authority.

<!-- handoff:g1-protocol-features -->
## g1-protocol-features

Primary detailed document: `docs/MODULE_DEVELOPMENT_GUIDE.md#g1-protocol-features`. Platform status: Feature orchestration is Dart; native layers provide platform transport and audio primitives. Evidence ceiling: Source validates framing and retry safety, not vendor command authority or physical display/notification behavior.

<!-- handoff:assistant-speech -->
## assistant-speech

Primary detailed document: `docs/MODULE_DEVELOPMENT_GUIDE.md#assistant-speech`. Platform status: iOS speech is conditional on permission/locale/device support; Android LC3 exists but PCM-to-ASR remains unavailable. Evidence ceiling: Provider tenancy, retention, abuse controls and physical latency/accuracy/privacy qualification remain external.

<!-- handoff:android-native -->
## android-native

Primary detailed document: `docs/MODULE_DEVELOPMENT_GUIDE.md#android-native`. Platform status: Android device target; PCM-to-ASR is explicitly unavailable in the current source candidate. Evidence ceiling: Builds and tests are E3 at most; Play Integrity, signing, OEM/device matrix and physical G1 evidence remain external.

<!-- handoff:ios-native -->
## ios-native

Primary detailed document: `docs/MODULE_DEVELOPMENT_GUIDE.md#ios-native`. Platform status: iOS device and simulator builds; speech depends on permission, locale and device capability. Evidence ceiling: Simulator/XCTest does not establish signed-device, App Attest, battery, thermal, locale matrix or physical G1 qualification.

<!-- handoff:digital-twin -->
## digital-twin

Primary detailed document: `docs/MODULE_DEVELOPMENT_GUIDE.md#digital-twin`. Platform status: Pure Dart deterministic test component. Evidence ceiling: Supplies E2 behavior only and cannot prove firmware, RF, timing, power, thermal or hardware compatibility.

<!-- handoff:model-gateway-service -->
## model-gateway-service

Primary detailed document: `docs/MODULE_DEVELOPMENT_GUIDE.md#model-gateway-service`. Platform status: Dependency-free Python development service. Evidence ceiling: Not a production AI service; provider tenancy, KMS references, abuse controls, observability and retention evidence remain external/source backlog.

<!-- handoff:identity-control-plane -->
## identity-control-plane

Primary detailed document: `docs/development/DURABLE_IDENTITY.md`. Platform status: Python reference APIs plus SQLite durable identity and an authenticated signing-broker client; trusted Linux verifier host required. Evidence ceiling: Durable source state and signature verification do not establish deployed KMS/HSM, platform attestation, account recovery, mobile lease integration or independent acceptance.

<!-- handoff:realtime-control-plane -->
## realtime-control-plane

Primary detailed document: `docs/development/HG0087_PRODUCTION_IMPLEMENTATION.md`. Platform status: Python reference APIs plus SQLite exact-attempt realtime custody, persistent revocation and a cleanup outbox on trusted local storage. Evidence ceiling: Source persistence and deterministic recovery tests do not establish a live provider exchange, authenticated service integration, remote cleanup or production latency.

<!-- handoff:capability-control-plane -->
## capability-control-plane

Primary detailed document: `docs/development/DURABLE_CAPABILITIES.md`. Platform status: Python reference APIs plus a SQLite intent ledger, durable single-use leases, bounded dispatch and readback-only crash recovery; not a sandbox. Evidence ceiling: The durable source runner is not a provider-specific OAuth adapter, authenticated ingress, encrypted payload vault, independently verified receipt or production qualification.

<!-- handoff:skills-registry -->
## skills-registry

Primary detailed document: `docs/development/SIGNED_SKILLS.md`. Platform status: Python legacy reference plus Linux Ed25519 package verification, exact inventory checks and a SQLite consent/version/revocation registry; no executor is installed. Evidence ceiling: Source checks establish signed-byte admission and local persistence only; actual sandbox/egress, external publisher trust/transparency, authenticated consent and independent package qualification remain open.

<!-- handoff:memory -->
## memory

Primary detailed document: `docs/MODULE_DEVELOPMENT_GUIDE.md#memory`. Platform status: Python in-memory reference plus Flutter process-memory answer history. Evidence ceiling: Does not provide encrypted durable storage, multi-device sync, regional retention, backup/deletion drills or independent privacy assurance.

<!-- handoff:codex-worker -->
## codex-worker

Primary detailed document: `docs/MODULE_DEVELOPMENT_GUIDE.md#codex-worker`. Platform status: Python launcher for an external Codex installation. Evidence ceiling: Dry-run source tests do not prove installed/authenticated Codex, container/seccomp, per-task identity, egress, quotas or compromise isolation.

<!-- handoff:mcp-adapter -->
## mcp-adapter

Primary detailed document: `docs/MODULE_DEVELOPMENT_GUIDE.md#mcp-adapter`. Platform status: Python stdio development adapter. Evidence ceiling: No production registration/authorization compatibility or live runtime connection is claimed.

<!-- handoff:qualification-release -->
## qualification-release

Primary detailed document: `docs/MODULE_DEVELOPMENT_GUIDE.md#qualification-release`. Platform status: Python qualification plus Android/iOS/Flutter/native CI lanes. Evidence ceiling: E0–E4 never manufacture physical, deployed, independent assurance, signing, pilot or store evidence.

<!-- handoff:contracts-compatibility -->
## contracts-compatibility

Primary detailed document: `docs/MODULE_DEVELOPMENT_GUIDE.md#contracts-compatibility`. Platform status: Contracts span Dart/Python and native adapters; vector coverage does not imply deployed consumer compatibility. Evidence ceiling: Source conformance is not production rollout, backward compatibility telemetry or provider/vendor certification.

<!-- handoff:repository-governance -->
## repository-governance

Primary detailed document: `docs/MODULE_DEVELOPMENT_GUIDE.md#repository-governance`. Platform status: GitHub repository governance plus deterministic local validators. Evidence ceiling: Source cannot apply/read inaccessible administrator settings, issue an independent review or merge itself.

<!-- handoff:native-dependencies -->
## native-dependencies

Primary detailed document: `docs/MODULE_DEVELOPMENT_GUIDE.md#native-dependencies`. Platform status: C/C++/Objective-C code compiled in Android and iOS paths. Evidence ceiling: Sanitizers and source digests do not prove exact upstream provenance, CVE response, binary reproducibility or physical audio quality.

<!-- handoff:external-evidence-authentication -->
## external-evidence-authentication

Primary detailed document: `docs/development/G9_TERMINAL_EXTERNAL_CLOSURE.md`. Platform status: Python trusted verifier on a controlled POSIX host. Evidence ceiling: The repository cannot create real issuer authority, out-of-band pin administration, independent acceptance or the facts described by external evidence.

<!-- handoff:latest-head-ci-custody -->
## latest-head-ci-custody

Primary detailed document: `docs/adr/ADR-0005-latest-head-ci-concurrency.md`. Platform status: GitHub Actions hosted runners. Evidence ceiling: CI custody cannot guarantee administrator protection settings, independent approval, physical/deployed evidence or merge authorization.

<!-- handoff:authority-quorum-review-integrity -->
## authority-quorum-review-integrity

Primary detailed document: `docs/development/G10_AUTHORITY_QUORUM_AND_REVIEW_INTEGRITY.md`. Platform status: Trusted POSIX verifier host with a controlled OS/runtime boundary. Evidence ceiling: Closes repository validation semantics only; real authorities, reviewers, trusted-host operation and evidence facts remain independently controlled.

<!-- handoff:agent-os-plugin -->
## agent-os-plugin

Primary detailed document: `plugins/hepta-glasses-agent-os/DEVELOPMENT.md`. Platform status: Host-plugin development integration with relative Python stdio launch. Evidence ceiling: No host compatibility, production authorization, runtime connectivity or physical effect is established by source packaging.
