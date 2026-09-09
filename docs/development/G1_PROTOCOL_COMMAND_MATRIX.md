# G1 command matrix, retry safety, and firmware compatibility boundary

Status: source contract supplement for `g1-transport` and `g1-protocol-features`.  
Machine contract: `contracts/g1-command-matrix-v1.json`.  
Validator: `services/qualification/g1_command_matrix.py`.  
Claim ceiling: source semantics only; vendor and physical confirmation remain required.

## 1. Purpose and authority boundary

This document centralizes every G1 command/event currently consumed by the application and gives each one an explicit direction, target leg, byte layout, packet bound, acknowledgement rule, retry classification, readback status, source implementation, test surface, and external gate.

The mobile edge runtime remains the final application authority for local effects. Native Android/iOS code owns platform BLE readiness and byte acceptance. G1 firmware owns physical interpretation and state. A command appearing in source does not prove that every firmware version implements it, that a write was applied, or that a returned byte has the assumed vendor meaning.

The authoritative effect identity remains:

```text
(pair identity,
 connection generation,
 side,
 caller idempotency key,
 SHA-256(device bytes))
```

The response owner and uncertain-write quarantine key remain:

```text
(connection generation, side, command byte)
```

A timeout or malformed response after native acceptance is indeterminate. It is never converted into a retryable failure merely because no success ACK was observed.

## 2. Transport and platform initialization

Both legs expose the same Nordic-UART-style service and phone-facing write/notify characteristics recorded in the base BLE contract. Pair readiness requires both legs independently ready.

Android currently performs service/characteristic discovery, CCCD enablement, MTU negotiation to at least 203 bytes, then attempts `[0xF4, 0x01]`. iOS enables notification and sends `[0x4D, 0x01]` through its bounded write path. Those platform-specific initialization bytes are source facts, not vendor-certified protocol facts; a firmware matrix and physical traces must confirm them.

## 3. Command summary

| ID | Byte | Direction | Target | Packet/payload bound | ACK/readback |
|---|---:|---|---|---|---|
| `microphone_on` | `0x0E` | phone → glasses | selected leg, normally right | 2 / 1 bytes | correlated `0xC9` or `0xCB`; no state readback |
| `microphone_data` | `0xF1` | glasses → phone | right leg in current source | 202 / 200 LC3 bytes | event, no ACK |
| `touch_and_assistant_event` | `0xF5` | glasses → phone | originating leg | vendor bounded | event, no ACK |
| `display_text_and_ai` | `0x4E` | phone → glasses | left then right | 200 / 191 UTF-8 bytes | per-packet ACK; no display readback |
| `bitmap_packet` | `0x15` | phone → glasses | one leg per transfer | 200 / 194 bytes | native acceptance, then finish/CRC |
| `bitmap_finish` | `0x20` | phone → glasses | active bitmap leg | 3 / 2 bytes | command plus `0xC9` |
| `bitmap_crc` | `0x16` | phone → glasses | active bitmap leg | 5 / 4 bytes | command plus byte-5 `0xC9` |
| `heartbeat` | `0x25` | phone → glasses | left then right | 6 / 5 bytes | command plus byte-4 type `0x04` |
| `exit_mode` | `0x18` | phone → glasses | left then right | 1 / 0 bytes | per-leg ACK; no mode readback |
| `notification_whitelist` | `0x04` | phone → glasses | left | 180 / 177 JSON bytes | per-packet ACK; no readback |
| `notification` | `0x4B` | phone → glasses | left | 180 / 176 JSON bytes | per-packet ACK; no readback |
| `serial_number_read` | `0x34` | phone → glasses | selected leg | request 1 byte | response ≥18 bytes; bytes 2–17 decoded |

The JSON contract contains the normative field descriptions and exact source/test references.

## 4. Framing details

### 4.1 Assistant and text display

A `0x4E` packet is:

```text
0     command = 0x4E
1     sync sequence
2     total packet count
3     packet sequence
4     new-screen/status byte
5..6  position, signed 16-bit big-endian
7     current page
8     maximum page
9..   UTF-8 payload, at most 191 bytes
```

Each packet is sent to the left leg and then the right leg. An accepted left sequence followed by any right-leg uncertainty is a degraded pair effect. Automatic or user-triggered paging must remain generation-fenced so a cancelled assistant cannot publish later pages.

### 4.2 Notification whitelist

A `0x04` frame uses:

```text
0     command
1     total packet count
2     packet sequence
3..   UTF-8 JSON payload, at most 177 bytes
```

The current source sends the whitelist to the left leg. The firmware-side JSON schema, persistence and propagation to the pair are not established by source.

### 4.3 Notification

A `0x4B` frame uses:

```text
0     command
1     message ID
2     total packet count
3     packet sequence
4..   UTF-8 JSON payload, at most 176 bytes
```

The eight-bit message ID may wrap. Wraparound is not an idempotency guarantee and does not authorize replay of an uncertain earlier notification.

### 4.4 Bitmap

The first `0x15` packet contains sequence zero, fixed storage address `00 1C 00 00`, and up to 194 image bytes. Later packets contain only command, sequence and payload. The application allows at most 256 packets.

Data packets use native write acceptance rather than a protocol ACK. After all are accepted, `0x20 0D 0E` requests transfer finalization. A `0x16` request supplies CRC-32/XZ of the storage address concatenated with the image, encoded big-endian. Missing finish or CRC acknowledgement after any data write is indeterminate. The application must not silently restart the full image.

### 4.5 Heartbeat

The request is:

```text
[0x25, 0x06, 0x00, sequence, 0x04, sequence]
```

The response must be correlated to command `0x25` and have type `0x04` at byte 4. Heartbeats do not overlap. Only a typed pre-write rejection may be retried; a post-acceptance timeout remains quarantined.

### 4.6 Audio

A microphone event must be exactly 202 bytes:

```text
0       0xF1
1       packet sequence
2..201  200 bytes LC3
```

Current source accepts audio only from the right leg. LC3 decode must produce exactly 3,200 bytes of 16-kHz, mono, signed-16 PCM. The decoder output is still generation/pair checked before entering the active speech session. Malformed, wrong-side, stale-attempt or stale-generation audio is discarded, not attached to a newer session.

## 5. Assistant event indices

For a correlated `0xF5` event, source recognizes:

- `0`: exit all device modes;
- `1`: manual page, left for previous and right for next;
- `23`: start assistant;
- `24`: recording complete.

Unknown indices produce bounded diagnostic metadata only. They cannot be reinterpreted as a privileged command. Vendor enumeration and physical touch behavior remain external.

## 6. Retry and uncertainty matrix

| Observation | Effect classification | Continuation |
|---|---|---|
| generation/pair/side mismatch before native write | rejected before write | reacquire current authority and retry within policy budget |
| side not ready or native explicitly rejects before acceptance | rejected before write | bounded retry only while authority remains unchanged |
| protocol data packet accepted, later packet rejected | indeterminate partial sequence | stop and reconcile; do not restart blindly |
| one leg committed, other leg uncertain | degraded/indeterminate pair effect | surface recovery; do not claim pair success |
| ACK timeout after native acceptance | indeterminate | retain command quarantine until late response, authoritative readback, generation retirement or terminal disposal |
| malformed or negative response after possible write | indeterminate unless vendor contract proves terminal non-application | investigate/read back; no automatic mutation replay |
| read-only serial response malformed | read failed | bounded read retry under unchanged authority; never use malformed bytes as identity |

## 7. Readback and reconciliation gaps

Current source lacks authoritative post-session readback for:

- display contents/page;
- microphone mode;
- device mode after exit;
- notification whitelist;
- notification delivery;
- persisted bitmap state after the active finish/CRC exchange.

These are protocol/product gaps, not reasons to weaken the runtime's indeterminate outcome. Preferred firmware evolution is to add an operation/effect ID and a side-specific state query whose response binds firmware version, pair/leg identity, generation or connection epoch, operation ID, payload digest and terminal disposition.

Until such support exists, the UI and operational tooling must present uncertainty and a safe recovery action rather than claiming failure.

## 8. Compatibility and versioning

The contract describes the current source profile, not a universal G1 firmware specification. Production compatibility requires a matrix of:

- G1 product/hardware revision;
- left and right firmware versions;
- command support and field semantics;
- initialization sequence;
- maximum MTU and packet size;
- ACK/NACK/error behavior;
- readback support;
- downgrade/upgrade behavior;
- Android/iOS application versions.

A field meaning, command byte, status meaning, packet bound, target leg, retry class or readback behavior change requires a new explicit contract revision and migration plan. Implementations may become more restrictive but must not silently widen accepted input or retry authority.

## 9. Verification

Run:

```bash
python3 -m services.qualification.g1_command_matrix
python3 -m unittest services.qualification.test_g1_command_matrix -v
flutter test test/runtime/packet_codec_test.dart
flutter test test/runtime/ble_manager_authority_test.dart
flutter test test/runtime/tool_effect_semantics_test.dart
```

The validator checks the closed command set, unique bytes, transport UUIDs, initialization values, response statuses, assistant events, framing bounds, repository references, tests, invariants and external gates against the base G1 BLE contract.

Tests prove source behavior only. The release candidate still requires Android/iOS native builds, sanitizers, signed physical traces, firmware identity and independent acceptance.

## 10. Change checklist

A protocol change must update, in one reviewed candidate:

1. `contracts/g1-command-matrix-v1.json` or its explicit successor;
2. `contracts/g1-ble-protocol-v1.json` where shared transport/authority semantics change;
3. Dart/Kotlin/Swift/native producer and consumer code;
4. cross-language golden vectors and malformed-input tests;
5. this document and the BLE connection guide;
6. firmware compatibility/migration notes;
7. module ownership/handoff records when interfaces or evidence ceilings change;
8. physical qualification scenarios and release evidence templates;
9. exact-head CI and artifact evidence.

No command is considered vendor-certified, physically reliable, safe to replay, or released merely because the source matrix validator passes.
