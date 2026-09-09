# `model-gateway-service` module engineering handoff

Canonical registry digest: `91c5f6fa9dcd5f6e4844cd6a022534c8da48b84bcb2db29601e0a83a7c03ab37`

Owner: `ai-platform`

Lifecycle: `development_reference`

Profile: `engineering-handoff-v1`

This generated handoff is a module-specific navigation and consistency surface. It does not replace the owner-authored primary document `docs/development/DURABLE_MODEL_GATEWAY.md` or manufacture deployment, physical-device, provider, signing, assurance, pilot, store, or release evidence.

## 1. Purpose and authority boundary

The module identifier is `model-gateway-service` and its accountable owner is `ai-platform`. Its current platform state is:

> Python provides authenticated framework-neutral ingress, SQLite v2 request custody and a fixed-endpoint text-only foreground Responses adapter; the Flutter client composes it through a runtime token-provider registry.

Implementation authority is limited to the source roots listed below. Anything outside those roots requires an explicit registry change and owner review. External gates remain non-source authorities and are never inferred from a green repository test.

### Source roots

- `services/model_gateway`
- `services/model_gateway/responses_provider.py`
- `services/model_gateway/recovery_inventory.py`
- `services/model_gateway/model_ingress.py`

## 2. Public interfaces and contracts

The primary engineering description is `docs/development/DURABLE_MODEL_GATEWAY.md`. The following contracts are the machine-readable interface and compatibility boundary for this module:

- `contracts/control-plane-v1.json`
- `contracts/durable-model-gateway-v2.json`
- `contracts/hg0087-production-v1.json`

The following documentation forms the reviewed human interface. A contract, schema, command, channel, API, storage layout, or externally visible behavior change must update every affected reference in the same candidate:

- `docs/MODULE_DEVELOPMENT_GUIDE.md#model-gateway-service`
- `services/model_gateway/README.md`
- `docs/development/MODULE_HANDOFF.md#model-gateway-service`
- `docs/development/DURABLE_MODEL_GATEWAY.md`
- `docs/operations/DURABLE_MODEL_GATEWAY_RUNBOOK.md`
- `docs/development/MODEL_RECOVERY_INVENTORY.md`
- `docs/development/AUTHENTICATED_MODEL_INGRESS.md`
- `docs/development/CRITICAL_TEST_DEPTH.md`

## 3. State, concurrency, and cancellation

State ownership, concurrency, cancellation, generation fencing, idempotency, and late-result behavior are defined jointly by the primary document, the registered source roots, and the contracts above. A change is inadmissible when those surfaces disagree. Unknown state, stale generation, expired authority, ambiguous ownership, or cancellation races must fail closed rather than silently commit a side effect.

## 4. Failure, recovery, and idempotency

The module must preserve explicit pre-effect failure, indeterminate-after-possible-effect, authoritative readback, retry, replay, and recovery semantics documented by its contracts. Recovery must not widen authority, restore revoked state, reuse a conflicting idempotency key, or convert missing evidence into success. Cross-module recovery changes require review from every affected owner.

## 5. Configuration, compatibility, and migration

Configuration and migration are source objects. Dependency, toolchain, schema, provider, platform, package identity, storage, policy, or firmware movement requires compatibility analysis and fresh qualification for the affected evidence axes. No historical Artifact, approval, physical report, provider receipt, signature, or release decision automatically transfers to a successor.

## 6. Operations, tests, observability, and SLO

The registered executable verification surfaces are:

- `services/model_gateway/test_app.py`
- `services/model_gateway/test_production.py`
- `services/model_gateway/test_model_boundaries.py`
- `services/model_gateway/test_responses_provider.py`
- `services/model_gateway/test_model_send_admission.py`
- `services/model_gateway/test_recovery_inventory.py`
- `services/model_gateway/test_model_ingress.py`
- `services/model_gateway/test_bounded_worker_determinism.py`

Tests prove only their declared environment and assertions. Operational acceptance additionally requires bounded logs, privacy-safe traces, stable error classes, relevant SLO measurements, rollback/recovery procedures, and exact candidate identity. Module owners must record negative-path evidence, not only successful examples.

## 7. Security, privacy, and evidence ceiling

The current evidence ceiling is:

> Source tests establish principal/body binding, local quota/idempotency/revocation and wire-contract behavior only; live identity/provider tenancy, retention, remote cancellation/recovery, encrypted metadata and independent qualification remain open.

The unresolved external or authority-owned boundaries are:

- production provider tenancy, KMS secret reference, quotas, retention and observability

Secrets, raw credentials, signing material, unrestricted mutation authority, and sensitive user content must not be introduced into source, prompts, ordinary logs, generated documentation, test fixtures that escape their boundary, or repository evidence packages.

## 8. Ownership and change protocol

A change touching a listed source root, contract, test, or primary document must update the canonical module record when ownership, interfaces, platform state, evidence ceiling, or external gates change. Run `python3 tools/generate_module_docs.py --check` and `python3 tools/validate_module_semantics.py`; obtain the applicable Code Owner review; run all seven canonical CI jobs on one unchanged head; and bind any promotion to fresh exact-head evidence. Administrator bypass, self-review, stale evidence reuse, or generated prose alone cannot approve the change.
