# `latest-head-ci-custody` module engineering handoff

Canonical registry digest: `dd65170c1f3264144d49a39eec4601f5245e6f2922ceaf51057f63cdb1eafb36`

Owner: `quality-gates`

Lifecycle: `source_candidate`

Profile: `engineering-handoff-v1`

This generated handoff is a module-specific navigation and consistency surface. It does not replace the owner-authored primary document `docs/adr/ADR-0005-latest-head-ci-concurrency.md` or manufacture deployment, physical-device, provider, signing, assurance, pilot, store, or release evidence.

## 1. Purpose and authority boundary

The module identifier is `latest-head-ci-custody` and its accountable owner is `quality-gates`. Its current platform state is:

> GitHub Actions hosted runners.

Implementation authority is limited to the source roots listed below. Anything outside those roots requires an explicit registry change and owner review. External gates remain non-source authorities and are never inferred from a green repository test.

### Source roots

- `.github/workflows/ci.yml`
- `tools/validate_production_authority.py`

## 2. Public interfaces and contracts

The primary engineering description is `docs/adr/ADR-0005-latest-head-ci-concurrency.md`. The following contracts are the machine-readable interface and compatibility boundary for this module:

- `contracts/release-gates-v1.json`
- `contracts/main-branch-protection-v1.json`

The following documentation forms the reviewed human interface. A contract, schema, command, channel, API, storage layout, or externally visible behavior change must update every affected reference in the same candidate:

- `docs/adr/ADR-0005-latest-head-ci-concurrency.md`
- `docs/development/G8_PRODUCTION_AUTHORITY_CLOSURE.md`
- `docs/development/MODULE_HANDOFF.md#latest-head-ci-custody`

## 3. State, concurrency, and cancellation

State ownership, concurrency, cancellation, generation fencing, idempotency, and late-result behavior are defined jointly by the primary document, the registered source roots, and the contracts above. A change is inadmissible when those surfaces disagree. Unknown state, stale generation, expired authority, ambiguous ownership, or cancellation races must fail closed rather than silently commit a side effect.

## 4. Failure, recovery, and idempotency

The module must preserve explicit pre-effect failure, indeterminate-after-possible-effect, authoritative readback, retry, replay, and recovery semantics documented by its contracts. Recovery must not widen authority, restore revoked state, reuse a conflicting idempotency key, or convert missing evidence into success. Cross-module recovery changes require review from every affected owner.

## 5. Configuration, compatibility, and migration

Configuration and migration are source objects. Dependency, toolchain, schema, provider, platform, package identity, storage, policy, or firmware movement requires compatibility analysis and fresh qualification for the affected evidence axes. No historical Artifact, approval, physical report, provider receipt, signature, or release decision automatically transfers to a successor.

## 6. Operations, tests, observability, and SLO

The registered executable verification surfaces are:

- `services/qualification/test_ci_latest_head_custody.py`
- `tools/validate_production_authority.py`

Tests prove only their declared environment and assertions. Operational acceptance additionally requires bounded logs, privacy-safe traces, stable error classes, relevant SLO measurements, rollback/recovery procedures, and exact candidate identity. Module owners must record negative-path evidence, not only successful examples.

## 7. Security, privacy, and evidence ceiling

The current evidence ceiling is:

> CI custody cannot guarantee administrator protection settings, independent approval, physical/deployed evidence or merge authorization.

The unresolved external or authority-owned boundaries are:

- GitHub-hosted runner availability
- administrator cancellation of runs created before the PR-level concurrency rule
- branch protection that requires all seven canonical contexts

Secrets, raw credentials, signing material, unrestricted mutation authority, and sensitive user content must not be introduced into source, prompts, ordinary logs, generated documentation, test fixtures that escape their boundary, or repository evidence packages.

## 8. Ownership and change protocol

A change touching a listed source root, contract, test, or primary document must update the canonical module record when ownership, interfaces, platform state, evidence ceiling, or external gates change. Run `python3 tools/generate_module_docs.py --check` and `python3 tools/validate_module_semantics.py`; obtain the applicable Code Owner review; run all seven canonical CI jobs on one unchanged head; and bind any promotion to fresh exact-head evidence. Administrator bypass, self-review, stale evidence reuse, or generated prose alone cannot approve the change.
