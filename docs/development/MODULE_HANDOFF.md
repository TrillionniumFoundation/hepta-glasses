# Module engineering handoff index

Status: active source-candidate supplement. The flattened registry is
`docs/MODULE_COVERAGE.json`; this index selects the primary detailed development
document for every one of its 26 modules. The machine mapping is
`docs/MODULE_HANDOFF.json`, and `tools/validate_module_handoff.py` verifies exact
identity/order, lifecycle, declared dimension profiles, source/test/contract
references, anchors, minimum document length and exact index/status agreement.
These are structural checks, not proof that every engineering dimension remains
semantically complete or current with every code change. Module-owner review is
required.

The primary documents remain authoritative; this file deliberately does not
duplicate their protocol, state-machine or security text. Source documentation
never promotes a reference implementation, simulator or CI result into physical,
deployed, independent-review or release evidence.

For identity, realtime, capability persistence, durable Memory and Codex worker
custody, the primary documents below supersede the older reference-only portions
of the base guide. A persistent or bounded component does not upgrade its entire
module or close HG-0087. Current remaining work is tracked in
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

Primary detailed document: `docs/MODULE_DEVELOPMENT_GUIDE.md#assistant-speech`. Platform status: iOS uses system speech when permission, locale and device support are present. Android contains a bounded ticket-bound PCM-to-ASR transport component, but the consumer start route remains fail-closed until authenticated bootstrap and stream integration are composed. Evidence ceiling: Source components do not establish live speech tenancy, authenticated ticket delivery, retention controls or physical latency/accuracy/privacy qualification.

<!-- handoff:android-native -->
## android-native

Primary detailed document: `docs/MODULE_DEVELOPMENT_GUIDE.md#android-native`. Platform status: Android device target with LC3 decoding and a bounded HTTPS PCM-to-ASR component; production speech activation remains disabled until authenticated ticket and decoded-stream integration are active. Evidence ceiling: Builds and tests are E3 at most; Play Integrity, signing, live speech-provider use, OEM/device matrices and physical G1 evidence remain external.

<!-- handoff:ios-native -->
## ios-native

Primary detailed document: `docs/MODULE_DEVELOPMENT_GUIDE.md#ios-native`. Platform status: iOS device and simulator builds; speech depends on permission, locale and device capability. Evidence ceiling: Simulator/XCTest does not establish signed-device, App Attest, battery, thermal, locale matrix or physical G1 qualification.

<!-- handoff:digital-twin -->
## digital-twin

Primary detailed document: `docs/MODULE_DEVELOPMENT_GUIDE.md#digital-twin`. Platform status: Pure Dart deterministic test component. Evidence ceiling: Supplies E2 behavior only and cannot prove firmware, RF, timing, power, thermal or hardware compatibility.

<!-- handoff:model-gateway-service -->
## model-gateway-service

Primary detailed document: `docs/development/DURABLE_MODEL_GATEWAY.md`. Platform status: Python deterministic ingress plus SQLite v2 request custody and a fixed-endpoint text-only foreground Responses adapter; authenticated production ingress is not connected. Evidence ceiling: Source tests establish local quota/idempotency/revocation and wire-contract behavior only; live tenancy, retention, remote cancellation/recovery, identity integration, encrypted metadata and independent qualification remain open.

<!-- handoff:identity-control-plane -->
## identity-control-plane

Primary detailed document: `docs/development/DURABLE_IDENTITY.md`. Platform status: Python reference APIs plus SQLite durable identity and an authenticated signing-broker client; trusted Linux verifier host required. Evidence ceiling: Durable source state and signature verification do not establish deployed KMS/HSM, platform attestation, account recovery, mobile lease integration or independent acceptance.

<!-- handoff:realtime-control-plane -->
## realtime-control-plane

Primary detailed document: `docs/development/REALTIME_ADMISSION.md`. Platform status: Python reference APIs plus SQLite realtime custody with an explicit trusted host clock, final admission-expiry checks and durable cleanup of expired activation results. Evidence ceiling: Local custody and deadline tests do not establish live provider exchange, authenticated ingress, session-lifetime enforcement, remote cleanup facts, anti-rollback or production latency.

<!-- handoff:capability-control-plane -->
## capability-control-plane

Primary detailed document: `docs/development/DURABLE_CAPABILITIES.md`. Platform status: Python reference APIs plus SQLite intent/lease/readback custody and a Google Calendar single-event HTTPS adapter with final pre-POST authority revalidation; no authenticated production ingress is connected. Evidence ceiling: Local source and wire tests do not establish an OAuth consent/refresh vault, live provider ownership, encrypted payload custody, process isolation, independent review or product qualification.

<!-- handoff:skills-registry -->
## skills-registry

Primary detailed document: `docs/development/SIGNED_SKILLS.md`. Platform status: Python legacy reference plus Linux Ed25519 package verification, exact inventory checks, SQLite consent/version/revocation, a restricted zero-egress R0 data VM and signed-log inclusion verification; arbitrary-code execution is not enabled. Evidence ceiling: Source checks establish signed-byte admission and restricted data execution only; arbitrary-code sandboxing, enforced nonempty egress, external publisher/log governance, authenticated consent and independent qualification remain open.

<!-- handoff:memory -->
## memory

Primary detailed document: `docs/development/DURABLE_MEMORY.md`. Platform status: Python includes a SQLite ciphertext-only durable Memory store with an external per-subject cipher/key-provider interface; Flutter answer history remains a separate default-off process-memory feature. Evidence ceiling: The repository fixture cipher is not a production key service; authenticated ingress, KMS/HSM-backed subject keys, backup anti-rollback, downstream deletion evidence and independent privacy qualification remain open.

<!-- handoff:codex-worker -->
## codex-worker

Primary detailed document: `services/codex_worker/README.md`. Platform status: Linux source includes a fixed-executable task supervisor, bounded process/output/resource custody and an exact-domain HTTPS broker; it still requires an external OS isolation boundary for arbitrary code. Evidence ceiling: Source tests do not prove installed/authenticated Codex, namespaces/seccomp/cgroups, broker-exclusive egress, per-task identity, compromise containment or independently qualified deployment.

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
