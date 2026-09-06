# Hepta Glasses — G1 dual-BLE connection and effect authority

> Chinese: [G1_BLE_CONNECTION.md](G1_BLE_CONNECTION.md)
>
> Status: current source specification for revision `2026-09-01-g8`. Physical hardware, firmware compatibility, latency, power, thermal, and soak claims still require E5 evidence.

## Product boundary

The G1 left and right legs are independent BLE peripherals. Flutter owns request correlation, retry semantics, idempotency scope, and uncertain-effect quarantine. Native Android/iOS code owns scanning, GATT readiness, bounded writes, notifications, and LC3 decoding. Models, Skills, MCP, Codex, and UI code are not final device-mutation authority.

```text
Hepta Runtime / Policy / Tool Gateway
                  |
                  v
EvenG1Transport
  pair + generation + side + caller key + payload digest
                  |
                  v
BleManager
  ACK owner and quarantine = generation + side + command
                  |
                  v
Android GATT callbacks / iOS immutable attempt delegates
                  |
                  v
G1 left leg + G1 right leg
```

The repository does not contain G1 firmware, bootloader, secure-boot, or signed OTA authority.

## Pair identity and readiness

Names such as `G1_45_L_xxx` and `G1_45_R_xxx` form `Pair_45`. `pairIdentity` is part of write authority, not merely a display label. Its long-term stability must still be verified against vendor documentation and physical devices.

Both legs retain independent connectivity, readiness, response ownership, quarantine, and receipts. Pair readiness requires both legs.

| Role | UUID |
|---|---|
| UART service | `6E400001-B5A3-F393-E0A9-E50E24DCCA9E` |
| Phone write | `6E400002-B5A3-F393-E0A9-E50E24DCCA9E` |
| Phone notifications | `6E400003-B5A3-F393-E0A9-E50E24DCCA9E` |

The machine-readable source contract is `contracts/g1-ble-protocol-v1.json`.

## Android authority

Each Android GATT callback captures a connection generation and verifies that its `BluetoothGatt` is still selected for the current pair. A stale callback closes its old GATT rather than mutating the new session.

A leg becomes ready only after service/characteristic discovery, notification descriptor acceptance, MTU of at least 203, and native acceptance of initialization bytes `[0xF4, 0x01]`. Normal writes use a bounded serialized queue. Before accepting bytes, native code verifies Flutter's `expectedGeneration` and `expectedPairIdentity` against current authority.

Decoded background work rechecks both generation and pair identity before publishing data to Flutter.

## iOS immutable connection attempts

Every leg and connection attempt owns:

```text
PeripheralAttemptToken {
  peripheralID,
  side,
  generation,
  attemptNonce
}
```

An attempt-specific retained delegate proxy forwards service, characteristic, notification, value, and write-readiness callbacks. A callback may mutate state only when its token is current, its generation matches, its peripheral identity matches, and the exact peripheral object remains selected for that side. An unknown peripheral has no side; there is no “not left means right” fallback.

Because central-manager terminal callbacks do not include a caller generation, cancelled peripheral identifiers enter `RetiredConnectionBarrier`. The same `CBPeripheral` cannot be assigned to a new attempt until the old `didFailToConnect` or `didDisconnectPeripheral` callback is consumed.

A leg becomes ready only after UART discovery, RX notification confirmation, and acceptance of initialization bytes `[0x4D, 0x01]`. Vendor or physical evidence must resolve the platform-specific initialization-byte authority.

## Composite idempotency identity

Receipts, in-flight coalescing, and payload claims use:

```text
(pairIdentity,
 connectionGeneration,
 side,
 callerIdempotencyKey,
 SHA256(deviceBytes))
```

This prevents a receipt from one leg, generation, or pair from suppressing a required write in another authority domain. Reusing the same complete scope with different bytes fails closed. Capacity exhaustion rejects new authority rather than evicting a current receipt and risking a duplicate effect.

Flutter captures pair/generation at operation start, checks them again before the platform call, and passes both values to native code for another pre-write assertion.

## ACK ownership and uncertain effects

An ACK owner and its late-response quarantine are keyed by:

```text
(connectionGeneration, side, commandByte)
```

If native accepted a write but the ACK times out, the result is indeterminate and `effectMayHaveOccurred=true`. The command cannot be replayed automatically.

Quarantine may be released only by a matching late response, authoritative reconciliation of the exact leg/command, retirement of that exact generation, or terminal process disposal. A disconnect on one leg cannot release quarantine held by the other leg.

| Result | Effect may have occurred | Retry rule |
|---|---:|---|
| Authority mismatch before write | No | Reacquire authority, then retry within budget |
| Side not ready or native refusal | No | Bounded retry may be allowed |
| ACK timeout | Yes | Reconcile; no blind replay |
| Native acceptance unknown | Yes | Reconcile; no blind replay |
| Success/continue ACK | Yes, accepted | Return the existing receipt |

Upper layers must preserve these typed semantics rather than reducing them to an ambiguous Boolean.

## Hostile regression matrix

The source test suite proves:

- a generation-N iOS token cannot own generation N+1;
- an unknown peripheral cannot fall through to right-leg authority;
- same-peripheral reconnect is blocked until the retired terminal callback is consumed;
- the same caller key is independent across side, generation, and pair;
- payload drift under the same authority scope fails closed;
- a right-leg uncertain write remains quarantined after a left-leg disconnect.

Test entry points:

- `test/runtime/even_g1_transport_authority_test.dart`
- `test/runtime/ble_request_slot_test.dart`
- `test/runtime/ble_manager_authority_test.dart`
- `ios/RunnerTests/RunnerTests.swift`

## Speech and external evidence ceiling

On iOS, a 200-byte LC3 payload decodes to 3200-byte PCM and only a framework-final transcript is accepted. Stale attempt callbacks cannot feed a current session. Android has LC3 decoding but no production PCM-to-ASR adapter, so voice activation fails closed.

Source code does not close real-G1 loss/reconnect behavior, callback timing distributions, protocol compatibility, latency, power, thermal, soak, pair-identity stability, Android ASR, iOS locale/device coverage, or vendor firmware/OTA authority.
