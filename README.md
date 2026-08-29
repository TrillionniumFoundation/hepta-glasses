# Hepta Glasses OS

Hepta Glasses OS is a distributed AI-native runtime for Even Realities G1-class smart glasses. The glasses provide low-power sensing, input, and display; the companion phone provides deterministic edge execution; a cloud control plane provides identity, short-lived model/realtime access, revocation, capability routing, and long-running tasks; isolated Codex workers provide coding-focused diagnosis and patch generation.

Model, realtime, Skill, MCP, and Codex output are proposals. Real side effects are admitted, journaled, executed, and reconciled by deterministic code.

## Current product boundary

This repository began as a Flutter companion application with Android/iOS BLE, LC3 audio, speech, and display integrations imported from Even Realities' demo. It is not the G1 bootloader or firmware source. Until vendor firmware authority exists, the product is a distributed OS spanning the G1 device, mobile edge runtime, control plane, capability adapters, and isolated workers.

## Canonical truth

- [`docs/HEPTA_GLASSES_CANONICAL_DEVELOPMENT_PLAN.md`](docs/HEPTA_GLASSES_CANONICAL_DEVELOPMENT_PLAN.md)
- [`docs/CURRENT_STATE.md`](docs/CURRENT_STATE.md)
- [`docs/PRODUCT_BOUNDARY.md`](docs/PRODUCT_BOUNDARY.md)
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- [`docs/GAP_LEDGER.yaml`](docs/GAP_LEDGER.yaml)
- [`docs/EVIDENCE_INDEX.yaml`](docs/EVIDENCE_INDEX.yaml)

## Implemented repository-side foundation

- versioned event, intent, task, tool, lease, display, realtime, memory, qualification, and release contracts;
- deterministic packet framing, G1 digital twin, dual-leg idempotency, retries, and degraded receipts;
- append-only hash-chained audit, recoverable task lifecycle, cancellation, policy, and Tool Gateway;
- provider-neutral mobile model gateway boundary;
- device registry, short-lived key-ID tokens, key rotation, rate limits, and token/session/device/subject revocation;
- one-time realtime bootstrap with scope/profile allowlists and generation-fenced barge-in;
- typed capability adapters, exact argument leases, Prompt Injection separation, journal-before-effect, and reconciliation;
- signed Skill registry, upgrade re-consent, revoke, purpose-bound Memory, TTL, export, and deletion;
- bounded Codex worker and read-only MCP development tools;
- Android/iOS physical trace evaluator, source SBOM/provenance, source/product release gate, and branch-protection automation;
- CI, negative tests, evidence templates, and operational runbooks.

## Validation

```bash
python3 tools/validate_repository.py
python3 -m unittest discover -s services -p 'test_*.py'
python3 -m unittest discover -s adapters -p 'test_*.py'
python3 -m compileall -q services adapters tools
flutter pub get
flutter analyze --no-fatal-infos --no-fatal-warnings
flutter test
```

CI additionally generates an exact-head source SBOM, provenance, and source release bundle.

## Security invariants

1. Codex, models, Flutter widgets, MCP clients, and Skills do not own permanent credentials, BLE authority, or final mutation authority.
2. Every mutation is journaled before effect and keyed for exact replay safety.
3. Decision leases are short-lived and subject/device/task/action/argument bound.
4. Untrusted content cannot authorize a mutation.
5. R4, unrestricted shell, credential reads, firmware flashing, payment, and account mutation are unavailable in the consumer profile.
6. Uncertain completion requires reconciliation; timeout is not interpreted as failure.
7. Physical-device and public-release claims require the machine-readable product release gate.

## External gates

Physical G1 qualification, vendor firmware/OTA access, production credentials and infrastructure, branch protection, independent reviews, signing identities, pilot telemetry, and rollout drills remain explicit external gates until their evidence exists. The repository supplies the runbooks and validators but does not fabricate those inputs.

## Upstream

The upstream import record is retained in [`UPSTREAM.md`](UPSTREAM.md), and the BSD-2-Clause notice remains in [`LICENSE`](LICENSE).
