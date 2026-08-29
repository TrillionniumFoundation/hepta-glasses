
# Hepta Glasses OS

Hepta Glasses OS is a distributed, AI-native runtime for Even Realities G1-class smart glasses.
The glasses provide low-power sensing, input, and display; the companion phone provides the
edge runtime and device capabilities; isolated cloud workers provide model and Codex specialist
execution. Model output is always a proposal. Real side effects are admitted, journaled,
executed, and reconciled by deterministic code.

## Current product boundary

This repository is currently a Flutter companion application plus Android/iOS native BLE,
LC3 audio, speech, and display integrations imported from Even Realities' demo application.
It is not the G1 firmware, bootloader, or a claim of a complete standalone glasses operating
system. The active work converts the companion application into the edge portion of the
system while retaining the upstream device protocol implementation.

Canonical entry points:

- [`docs/HEPTA_GLASSES_CANONICAL_DEVELOPMENT_PLAN.md`](docs/HEPTA_GLASSES_CANONICAL_DEVELOPMENT_PLAN.md)
- [`docs/CURRENT_STATE.md`](docs/CURRENT_STATE.md)
- [`docs/PRODUCT_BOUNDARY.md`](docs/PRODUCT_BOUNDARY.md)
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- [`docs/GAP_LEDGER.yaml`](docs/GAP_LEDGER.yaml)
- [`docs/EVIDENCE_INDEX.yaml`](docs/EVIDENCE_INDEX.yaml)

## Implemented foundation

The source tree now contains:

- versioned Agent, task, tool, lease, display, and skill schemas;
- a deterministic packet fragmenter and G1 digital twin;
- a dual-leg write coordinator with bounded retries and idempotency;
- an append-only hash-chained audit journal;
- a recoverable task state machine;
- a deny-by-default capability and decision-lease policy engine;
- a journal-before-effect tool gateway with replay-safe receipts;
- a backend model-gateway boundary with no vendor API key in the mobile client;
- a bounded Codex worker launcher that permits only read-only or workspace-write sandboxes;
- a read-only MCP development surface;
- repository validation, Python tests, Flutter tests, and CI.

These source-level mechanisms do not substitute for real-device, production-credential,
firmware-signing, privacy, or pilot evidence. Exact remaining external blockers are tracked in
the Gap Ledger.

## Development checks

```bash
python3 tools/validate_repository.py
python3 -m unittest discover -s services -p 'test_*.py'
python3 -m unittest discover -s adapters -p 'test_*.py'
flutter pub get
flutter analyze --no-fatal-infos --no-fatal-warnings
flutter test
```

## Security invariants

1. Codex, realtime models, Flutter widgets, and MCP clients do not directly own BLE handles,
   permanent credentials, or final mutation authority.
2. Every mutation is journaled before effect and keyed for idempotent replay.
3. A decision lease is short-lived, task-bound, device-bound, action-bound, and cannot be
   extended by model output.
4. R4 operations, unrestricted shell, credential reads, firmware flashing, payment, and account
   mutation are unavailable in the consumer profile.
5. Uncertain completion triggers reconciliation; timeout is never interpreted as proof of failure.

## Upstream

The repository retains the upstream attribution and import record in [`UPSTREAM.md`](UPSTREAM.md).
The upstream BSD-2-Clause notice remains in [`LICENSE`](LICENSE).
