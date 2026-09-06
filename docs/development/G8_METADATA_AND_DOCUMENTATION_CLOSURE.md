# G8 metadata integrity and module-documentation closure

Status: repository-side implementation record for canonical revision `2026-09-01-g8`.

This package closes repository-actionable audit findings in the Gap Ledger, module documentation, mobile composition root, and digital-twin authority. It is not exact-head E4 evidence, physical-device qualification, deployed-infrastructure evidence, independent approval, or product-release evidence.

## 1. Gap evidence integrity

The prior Gap Ledger accepted a non-empty evidence string without proving that the referenced path existed. Several `CLOSED_SOURCE` rows therefore pointed at removed or renamed files. Revision v6 replaces those references with current source, tests, or an explicit `REMOVED_FROM_PRODUCT_BOUNDARY` closure.

`tools/validate_repository_metadata.py` now independently enforces:

- canonical plan revision and allowed status semantics;
- unique gap IDs and non-empty owners;
- existence of every `CLOSED_SOURCE` or `CLOSED_VERIFIED` evidence file;
- existence of every blocked or open source-resume file;
- explicit evidence requirement and unblock condition for external/admin/upstream rows;
- explicit close criteria for any future `OPEN` source gap;
- no repository-actionable `OPEN` row at source-exit time;
- no hard-coded requirement that selected IDs be declared closed irrespective of evidence.

The validator runs in the read-only `repository-contracts` CI job. A missing file, stale rename, malformed ledger, or undocumented source gap fails the exact-head matrix.

## 2. Removed legacy capabilities

Historical rows for social posting, mobile OCR, and a separate `hepta_dashboard` no longer pretend that deleted paths are implementations. `docs/PRODUCT_BOUNDARY.md` now records that these are absent from the supported current product. Their rows are closed only as `REMOVED_FROM_PRODUCT_BOUNDARY` and cite the product boundary plus module registry.

Reintroducing one of these capabilities requires a new module, owner, schema, risk tier, data-class/privacy design, policy rule, exact approval, receipt/reconciliation behavior, tests, documentation, and external evidence where applicable.

## 3. Complete module documentation contract

`docs/MODULES.json` declares 22 major modules. Each module has:

- stable ID and owner;
- lifecycle truth (`source_candidate` or `development_reference`);
- one or more existing source roots;
- an exact detailed section in `docs/MODULE_DEVELOPMENT_GUIDE.md`;
- existing deterministic tests;
- existing contracts or schemas;
- explicit external evidence gates.

The guide covers mobile shell, runtime, policy/Tool Gateway, durable audit, G1 transport, device features, assistant/speech, Android, iOS, digital twin, model gateway, identity, realtime, capability adapters, Skills, Memory, Codex, MCP, qualification/release, compatibility, governance, and native dependencies.

The metadata validator compares the registry IDs and order with exact guide markers, enforces a minimum substantive section size, and fails on missing source, documentation, test, or contract references. `docs/README.md` and `docs/EVIDENCE_INDEX.yaml` must index the registry and validator.

## 4. Mobile composition root

`lib/bootstrap/hepta_bootstrap.dart` is the single mobile composition root for:

- platform-authenticated durable audit;
- fail-closed or explicit-development mutation authority;
- deterministic runtime construction;
- display, microphone, exit, notification, whitelist, and bitmap effect adapters.

`lib/main.dart` now delegates runtime construction to this composition root. Widgets and feature services consume `HeptaRuntime.current`; they do not instantiate policy, audit, or authority dependencies. Failure to establish durable state leaves all assistant and device mutations disabled.

## 5. Retry-safety regressions

New deterministic contract tests establish that:

- microphone activation retries only a typed `retrySafe` pre-write failure;
- an uncertain microphone write stops instead of consuming another effect authority;
- each microphone attempt is included in the exact runtime arguments and lease digest;
- heartbeat retries are gated by `retrySafe` and never replay an indeterminate native write.

These tests replace stale Gap Ledger references with executable source evidence.

## 6. Digital-twin authority parity

`G1DigitalTwin` now uses an authoritative pair identity, positive connection generation, side, caller key, and payload SHA-256. It returns an existing receipt only inside the same complete identity, fails payload drift inside one scope, and retires prior receipts when generation or pair changes.

New tests prove cross-side, cross-generation, and cross-pair separation, same-identity replay without another write, and payload-drift rejection. The twin remains synthetic E2 evidence and cannot close physical G1 behavior.

## 7. Audit truth reconciliation

Current State and the module guide now match the implemented `authenticated-checkpoint-v3` design:

- startup, read, and explicit verification authenticate the complete chain;
- append may use a bounded authenticated-tail fast path only when the process-trusted checkpoint, platform MAC, file metadata, length, and terminal record agree;
- any trust or metadata drift triggers a full-chain verification before append;
- the design does not claim that every ordinary append rescans every historical byte;
- production assurance may add periodic full verification, immutable segments, remote/WORM anchoring, or a trusted monotonic root.

## 8. Source exit and evidence ceiling

Repository-side closure is E0-E3 until one unchanged live PR head completes all seven required jobs:

1. `repository-contracts`
2. `flutter`
3. `android-native`
4. `ios-native`
5. `native-sanitizers`
6. `secret-and-boundary-scan`
7. `source-evidence`

The resulting `hepta-source-evidence-<exact-head-sha>` artifact must bind the same commit and tree and pass independent content inspection. Any subsequent source push invalidates that E4 record.

Physical G1 traces, production KMS/HSM and attestation, provider credential revocation, real model/realtime/OAuth adapters, vendor firmware authority, complete GitHub administration, independent assurance, binary signing, pilot, rollout, rollback, store approval, and product release remain external, administrative, or upstream gates. No source change in this package claims to close them.
