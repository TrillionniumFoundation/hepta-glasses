# `agent-os-plugin` module engineering handoff

Canonical registry digest: `3892bc13b99d363c59985d37dd15ba4deabdb2b5ef2f4ad13ef7bce73737181c`

Owner: `developer-platform`

Lifecycle: `development_reference`

Profile: `engineering-handoff-v1`

This generated handoff is a module-specific navigation and consistency surface. It does not replace the owner-authored primary document `plugins/hepta-glasses-agent-os/DEVELOPMENT.md` or manufacture deployment, physical-device, provider, signing, assurance, pilot, store, or release evidence.

## 1. Purpose and authority boundary

The module identifier is `agent-os-plugin` and its accountable owner is `developer-platform`. Its current platform state is:

> Host-plugin development integration with relative Python stdio launch.

Implementation authority is limited to the source roots listed below. Anything outside those roots requires an explicit registry change and owner review. External gates remain non-source authorities and are never inferred from a green repository test.

### Source roots

- `plugins/hepta-glasses-agent-os`

## 2. Public interfaces and contracts

The primary engineering description is `plugins/hepta-glasses-agent-os/DEVELOPMENT.md`. The following contracts are the machine-readable interface and compatibility boundary for this module:

- `plugins/hepta-glasses-agent-os/.mcp.json`
- `schemas/tool-request.schema.json`
- `schemas/tool-receipt.schema.json`

The following documentation forms the reviewed human interface. A contract, schema, command, channel, API, storage layout, or externally visible behavior change must update every affected reference in the same candidate:

- `plugins/hepta-glasses-agent-os/DEVELOPMENT.md`
- `docs/development/MODULE_HANDOFF.md#agent-os-plugin`

## 3. State, concurrency, and cancellation

State ownership, concurrency, cancellation, generation fencing, idempotency, and late-result behavior are defined jointly by the primary document, the registered source roots, and the contracts above. A change is inadmissible when those surfaces disagree. Unknown state, stale generation, expired authority, ambiguous ownership, or cancellation races must fail closed rather than silently commit a side effect.

## 4. Failure, recovery, and idempotency

The module must preserve explicit pre-effect failure, indeterminate-after-possible-effect, authoritative readback, retry, replay, and recovery semantics documented by its contracts. Recovery must not widen authority, restore revoked state, reuse a conflicting idempotency key, or convert missing evidence into success. Cross-module recovery changes require review from every affected owner.

## 5. Configuration, compatibility, and migration

Configuration and migration are source objects. Dependency, toolchain, schema, provider, platform, package identity, storage, policy, or firmware movement requires compatibility analysis and fresh qualification for the affected evidence axes. No historical Artifact, approval, physical report, provider receipt, signature, or release decision automatically transfers to a successor.

## 6. Operations, tests, observability, and SLO

The registered executable verification surfaces are:

- `services/qualification/test_source_coverage.py`
- `adapters/mcp/test_mcp_server.py`

Tests prove only their declared environment and assertions. Operational acceptance additionally requires bounded logs, privacy-safe traces, stable error classes, relevant SLO measurements, rollback/recovery procedures, and exact candidate identity. Module owners must record negative-path evidence, not only successful examples.

## 7. Security, privacy, and evidence ceiling

The current evidence ceiling is:

> No host compatibility, production authorization, runtime connectivity or physical effect is established by source packaging.

The unresolved external or authority-owned boundaries are:

- Host plugin installation and compatibility qualification; no physical effects or production credentials permitted

Secrets, raw credentials, signing material, unrestricted mutation authority, and sensitive user content must not be introduced into source, prompts, ordinary logs, generated documentation, test fixtures that escape their boundary, or repository evidence packages.

## 8. Ownership and change protocol

A change touching a listed source root, contract, test, or primary document must update the canonical module record when ownership, interfaces, platform state, evidence ceiling, or external gates change. Run `python3 tools/generate_module_docs.py --check` and `python3 tools/validate_module_semantics.py`; obtain the applicable Code Owner review; run all seven canonical CI jobs on one unchanged head; and bind any promotion to fresh exact-head evidence. Administrator bypass, self-review, stale evidence reuse, or generated prose alone cannot approve the change.
