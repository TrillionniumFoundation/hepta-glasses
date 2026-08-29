
# Architecture

```text
G1 left/right legs
  microphone / touch / display / state
                |
                | bounded BLE packets + ACK/timeout
                v
Device HAL + DualLegCoordinator
                |
                | versioned runtime contracts
                v
Edge Runtime
  EventBus / TaskEngine / AuditJournal / PolicyEngine
  ToolGateway / DisplayComposer / Context minimizer / Recovery
        |                                  |
        | capability tools                 | short-lived authenticated API
        v                                  v
Phone capabilities                    Cloud control plane
calendar / notifications              identity / model gateway / task service
location / reminders                  revocation / rate limits / Codex allocator
                                           |
                                  isolated Codex workers
```

## Core data path

```text
GlassesEvent
  -> context minimization
  -> AgentIntent proposal
  -> tool lookup and schema validation
  -> policy and lease evaluation
  -> journal decision
  -> journal mutation preparation
  -> deterministic handler
  -> authoritative reconciliation
  -> ToolReceipt
  -> DisplayCard pages
```

## Runtime packages

- `runtime/contracts.dart` — typed task, tool, lease, display, and policy objects.
- `runtime/audit_journal.dart` — append-only hash chain and integrity verification.
- `runtime/task_engine.dart` — recoverable state machine and idempotent creation.
- `runtime/policy_engine.dart` — deny-by-default risk and lease evaluation.
- `runtime/tool_gateway.dart` — sole source-level mutation boundary.
- `runtime/device_hal.dart` — transport-neutral G1 device boundary.
- `runtime/packet_codec.dart` — bounded deterministic packet framing.
- `runtime/dual_leg_coordinator.dart` — mirrored writes and degraded-state receipt.
- `runtime/model_gateway.dart` — backend-only provider boundary.
- `runtime/display_composer.dart` — bounded display-page composition.
- `simulator/g1_digital_twin.dart` — deterministic device and fault simulator.

## Two AI lanes

The reflex lane handles low-latency voice, translation, read-only queries, and bounded R0/R1 tools.
The deliberative lane creates durable tasks and assigns coding-focused work to isolated Codex
workers. The lanes share contracts and receipts but not execution authority or latency budgets.

## Failure semantics

- Timeout is indeterminate, not proof of failure.
- Duplicate idempotency keys with the same fingerprint replay the existing receipt.
- Duplicate keys with a different fingerprint fail closed.
- One-leg success produces a degraded receipt and requires reconciliation.
- Invalid journal linkage prevents recovery.
- Expired, mismatched, or consumed leases deny execution.
- User cancellation is durable and propagates before more side effects are admitted.
