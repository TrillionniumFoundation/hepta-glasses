
# Capability and decision-lease model

## Risk tiers

| Tier | Examples | Default admission |
|---|---|---|
| R0 | device state, time, read-only task state | authenticated session |
| R1 | display card, dismiss, local view mode | authenticated session and audit |
| R2 | reminder/calendar draft commit | user-present, exact single-use lease |
| R3 | message send, one-time location share, account-sensitive action | exact lease plus biometric proof |
| R4 | shell, credential read, firmware flash, payment, unrestricted account mutation | denied in consumer profile |

## Lease properties

A `DecisionLease` is:

- bound to one subject, device, task, and set of actions;
- bounded by exact argument constraints;
- issued and expired using UTC time;
- short-lived and normally single-use;
- consumed by deterministic code before an admitted side effect;
- unable to be renewed, widened, or self-issued by model output.

## Tool registration

A tool is unavailable until its `ToolSpec` declares its name, risk tier, mutation status, and
biometric requirement. Runtime code registers a handler separately. Unknown names, missing
handlers, stale deadlines, malformed requests, and policy uncertainty fail closed.

## Replay

A request carries an idempotency key and canonical fingerprint. Repeating the same key and
fingerprint returns the prior receipt. Reusing a key for a different request is a conflict and
never reaches a handler.
