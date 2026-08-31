# Hepta Glasses — G1 dual-BLE connection and protocol implementation

> Chinese: [G1_BLE_CONNECTION.md](G1_BLE_CONNECTION.md)
>
> Status: current source description. Hardware, firmware, and performance claims still require physical-G1 E5 evidence.

## 1. Product boundary

The G1 left and right legs are independent BLE peripherals. Flutter owns orchestration, request correlation, retry semantics, and session state. Native Android/iOS code owns scanning, GATT readiness, bounded writes, notifications, and LC3 decoding. This repository does not contain G1 firmware, bootloader, or signed OTA authority.

## 2. Layers

```text
Flutter UI / Assistant
        |
        v
BleManager + Hepta Runtime
  generation / request owner / quarantine / receipt
        |
        v
MethodChannel("method.bluetooth")
        |
        +-- Android BleManager.kt + BleDevice.kt
        |
        +-- iOS BluetoothManager.swift
        |
        v
G1 Left BLE + G1 Right BLE
```

Downlink uses `method.bluetooth`; binary uplink uses `eventBleReceive`; iOS speech finality uses `eventSpeechRecognize`. Native status reaches Flutter through `glassesConnecting`, `glassesConnected`, `glassesDisconnected`, and `foundPairedGlasses`.

## 3. Advertising and pairing

Names use four components, for example `G1_45_L_xxx` and `G1_45_R_xxx`. A `Pair_<channel>` is exposed only after both sides for a channel are found. Per-leg connectivity and readiness remain independent; one-leg success is not pair success.

## 4. GATT contract

| Role | UUID |
|---|---|
| UART service | `6E400001-B5A3-F393-E0A9-E50E24DCCA9E` |
| Phone write | `6E400002-B5A3-F393-E0A9-E50E24DCCA9E` |
| Phone notify subscription | `6E400003-B5A3-F393-E0A9-E50E24DCCA9E` |

The machine-readable contract is `contracts/g1-ble-protocol-v1.json`.

## 5. Android readiness state machine

1. Validate Bluetooth and runtime permission, then scan.
2. Call `connectGatt(autoConnect=false)` independently for each leg.
3. Discover the UART service, read/write characteristics, and CCCD; any missing component fails closed.
4. After the CCCD write succeeds, request MTU 251; the negotiated MTU must be at least 203.
5. Mark a leg ready only after native acceptance of initialization bytes `[0xF4, 0x01]`.
6. Emit `glassesConnected` only when both legs are ready.

Each connection captures a generation. Stale GATT callbacks are closed rather than applied to the new session. Normal writes enter a serialized queue of capacity 128; full queue, unready GATT, or native rejection returns failure.

## 6. iOS readiness state machine

1. Scan and form left/right pairs by channel.
2. Connect both `CBPeripheral` objects and discover UART service and characteristics.
3. Add a leg to the ready set only after RX notification is confirmed enabled.
4. Enqueue initialization bytes `[0x4D, 0x01]` through the bounded write path.
5. Emit `glassesConnected` only when both legs are ready.

Intentional disconnect does not auto-reconnect. Unexpected disconnect removes readiness and pending writes and reports a degraded snapshot to Flutter. The platform initialization bytes differ and require vendor firmware documentation or physical traces for authoritative confirmation.

## 7. Flutter request correlation

A response owner is keyed by:

```text
(connection generation, side L/R, command byte)
```

Only one owner may exist for a key. When native accepted a write but the ACK times out, completion is `indeterminate` and the key enters late-response quarantine; timeout is never treated as certain failure followed by blind replay. Generation replacement, disconnect, and dispose close pending requests with effect-may-have-occurred semantics.

Heartbeat uses one-shot rescheduling so calls cannot overlap. Pair connectivity is `left_connected && right_connected`.

## 8. Speech path

- iOS: each 200-byte LC3 payload decodes to 3200-byte PCM and feeds on-device Speech. Only a framework-final transcript is emitted; timed-out partial text is discarded.
- Android: LC3 decoding exists, but no production PCM-to-ASR adapter is configured. `startEvenAI` fails closed, so Android voice assistant availability must not be claimed.

## 9. Key commands

| Function | Command |
|---|---|
| Microphone control | `0x0E` |
| Microphone data | `0xF1` |
| TouchBar / assistant event | `0xF5` |
| AI and text display | `0x4E` |
| BMP packet / finish / CRC | `0x15` / `0x20` / `0x16` |
| Heartbeat | `0x25` |
| Exit mode | `0x18` |
| Notification / whitelist | `0x4B` / `0x04` |

Success is `0xC9`; selected multi-packet paths also accept `0xCB` as continue/accepted. Field widths, packet sizes, and display states are normative in the machine contract.

## 10. Disconnect and cleanup

Android calls `disconnect()` and `close()`, clears the write queue, and drops characteristic references. iOS cancels peripheral connections and clears characteristics, ready identifiers, and pending writes. Flutter stops heartbeat, fail-closes pending requests, and publishes a per-leg snapshot.

## 11. Claims not closed by source

External evidence is still required for real-G1 packet loss/reconnect, latency, power, thermal and soak; firmware compatibility; authoritative initialization commands; Android ASR; iOS locale/device coverage; and vendor firmware, bootloader, secure boot, OTA, recovery, and rollback authority.

## 12. Source index

- `lib/ble_manager.dart`
- `lib/services/proto.dart`
- `lib/services/evenai.dart`
- `android/app/src/main/kotlin/com/example/demo_ai_even/bluetooth/BleManager.kt`
- `android/app/src/main/kotlin/com/example/demo_ai_even/model/BleDevice.kt`
- `ios/Runner/BluetoothManager.swift`
- `ios/Runner/SpeechStreamRecognizer.swift`
- `contracts/g1-ble-protocol-v1.json`
- `docs/PLATFORM_CAPABILITIES.json`
