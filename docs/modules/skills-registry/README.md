# `skills-registry` module engineering handoff

Canonical registry digest: `2a5dccc20912cba3232e7f1738ea79f06a01cec0ffab68d1629a37efb90ac59b`

Owner: `skills`

Lifecycle: `development_reference`

Profile: `engineering-handoff-v1`

This generated handoff is a module-specific navigation and consistency surface. It does not replace the owner-authored primary document `docs/development/SIGNED_SKILLS.md` or manufacture deployment, physical-device, provider, signing, assurance, pilot, store, or release evidence.

## 1. Purpose and authority boundary

The module identifier is `skills-registry` and its accountable owner is `skills`. Its current platform state is:

> Python legacy reference plus Linux Ed25519 package verification, exact inventory checks, SQLite consent/version/revocation, a restricted zero-egress R0 data VM and signed-log inclusion verification; arbitrary-code execution is not enabled.

Implementation authority is limited to the source roots listed below. Anything outside those roots requires an explicit registry change and owner review. External gates remain non-source authorities and are never inferred from a green repository test.

### Source roots

- `services/skills/registry.py`
- `services/skills/__init__.py`
- `services/skills/signed_package.py`
- `services/skills/signed_registry.py`
- `services/skills/signed_registry_schema.py`
- `services/skills/data_vm.py`
- `services/skills/package_transparency.py`
- `services/skills/package_vault.py`
- `services/skills/sandbox_runtime.py`
- `services/skills/skill_service.py`

## 2. Public interfaces and contracts

The primary engineering description is `docs/development/SIGNED_SKILLS.md`. The following contracts are the machine-readable interface and compatibility boundary for this module:

- `schemas/skill-manifest.schema.json`
- `contracts/signed-skill-package-v1.json`
- `contracts/data-skill-runtime-v1.json`
- `contracts/signed-skill-transparency-v1.json`

The following documentation forms the reviewed human interface. A contract, schema, command, channel, API, storage layout, or externally visible behavior change must update every affected reference in the same candidate:

- `docs/MODULE_DEVELOPMENT_GUIDE.md#skills-registry`
- `docs/CAPABILITY_MODEL.md`
- `docs/development/MODULE_HANDOFF.md#skills-registry`
- `docs/development/SIGNED_SKILLS.md`
- `docs/operations/SIGNED_SKILLS_RUNBOOK.md`
- `docs/development/SIGNED_SKILL_SCHEMA_INTEGRITY.md`
- `docs/operations/SIGNED_SKILL_SCHEMA_RUNBOOK.md`
- `docs/development/DATA_SKILL_RUNTIME.md`
- `docs/operations/DATA_SKILL_RUNTIME_RUNBOOK.md`
- `docs/development/PACKAGE_TRANSPARENCY.md`
- `docs/operations/PACKAGE_TRANSPARENCY_RUNBOOK.md`

## 3. State, concurrency, and cancellation

State ownership, concurrency, cancellation, generation fencing, idempotency, and late-result behavior are defined jointly by the primary document, the registered source roots, and the contracts above. A change is inadmissible when those surfaces disagree. Unknown state, stale generation, expired authority, ambiguous ownership, or cancellation races must fail closed rather than silently commit a side effect.

## 4. Failure, recovery, and idempotency

The module must preserve explicit pre-effect failure, indeterminate-after-possible-effect, authoritative readback, retry, replay, and recovery semantics documented by its contracts. Recovery must not widen authority, restore revoked state, reuse a conflicting idempotency key, or convert missing evidence into success. Cross-module recovery changes require review from every affected owner.

## 5. Configuration, compatibility, and migration

Configuration and migration are source objects. Dependency, toolchain, schema, provider, platform, package identity, storage, policy, or firmware movement requires compatibility analysis and fresh qualification for the affected evidence axes. No historical Artifact, approval, physical report, provider receipt, signature, or release decision automatically transfers to a successor.

## 6. Operations, tests, observability, and SLO

The registered executable verification surfaces are:

- `services/skills/test_registry.py`
- `services/skills/test_signed_registry.py`
- `services/skills/test_signed_registry_schema.py`
- `services/skills/test_data_vm.py`
- `services/skills/test_package_transparency.py`
- `services/skills/test_package_vault.py`
- `services/skills/test_sandbox_runtime.py`
- `services/skills/test_skill_service.py`

Tests prove only their declared environment and assertions. Operational acceptance additionally requires bounded logs, privacy-safe traces, stable error classes, relevant SLO measurements, rollback/recovery procedures, and exact candidate identity. Module owners must record negative-path evidence, not only successful examples.

## 7. Security, privacy, and evidence ceiling

The current evidence ceiling is:

> Source checks establish signed-byte admission and restricted data execution only; arbitrary-code sandboxing, enforced nonempty egress, external publisher/log governance, authenticated consent and independent qualification remain open.

The unresolved external or authority-owned boundaries are:

- asymmetric trust roots, encrypted package store, execution sandbox and independent review

Secrets, raw credentials, signing material, unrestricted mutation authority, and sensitive user content must not be introduced into source, prompts, ordinary logs, generated documentation, test fixtures that escape their boundary, or repository evidence packages.

## 8. Ownership and change protocol

A change touching a listed source root, contract, test, or primary document must update the canonical module record when ownership, interfaces, platform state, evidence ceiling, or external gates change. Run `python3 tools/generate_module_docs.py --check` and `python3 tools/validate_module_semantics.py`; obtain the applicable Code Owner review; run all seven canonical CI jobs on one unchanged head; and bind any promotion to fresh exact-head evidence. Administrator bypass, self-review, stale evidence reuse, or generated prose alone cannot approve the change.
