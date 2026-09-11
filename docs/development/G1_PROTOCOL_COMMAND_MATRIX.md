# G1 typed command, wire, effect and readback matrix

Status: source contract; vendor semantics and physical qualification remain external.  
Machine contract: `contracts/g1-command-matrix-v1.json` (`schema_version=2`).  
Validator entry point: `services/qualification/g1_command_matrix.py`.  
Validation implementation: `services/qualification/g1_command_matrix_impl.py`.  
Regression: `services/qualification/test_g1_command_matrix.py`.

## 1. Normative boundary

The JSON contract is normative. This document explains its closed types and claim ceiling; it does not override byte fields, bounds, response predicates or effect dispositions in the machine record.

Schema version 2 replaces the former prose-only command descriptions with a closed profile for every command or event:

- command identity, direction, operation class, target and aggregation;
- first/subsequent frame bounds, payload offsets, payload bounds and encoding;
- frame count representation and maximum, with an explicit reason whenever a maximum is not asserted;
- named wire fields with offsets, widths, encoding, constants and equality relations;
- response bounds, status predicates and payload locations;
- pre-write, post-write, malformed-response, negative-response and partial-progress dispositions;
- automatic/manual retry authority;
- readback kind, scope and whether it is authoritative for mutated state;
- exact source bindings, tests, external gates and executable producer/consumer examples.

Unknown fields, duplicate JSON keys, duplicate command bytes, missing source fragments, coordinated bound drift and count-preserving profile swaps fail closed.

## 2. Authority and correlation

A request owner is:

```text
(connection_generation, side, command)
```

Mutation authority is:

```text
(pair_identity,
 connection_generation,
 side,
 caller_idempotency_key,
 payload_sha256)
```

Both lists are compared byte-for-byte with `contracts/g1-ble-protocol-v1.json`. A native-accepted write followed by timeout is `indeterminate_effect_may_have_occurred`, not a retry-safe failure. Pair commands require both legs; one-leg success is a degraded or indeterminate pair result. Fragmented transfers become partial/indeterminate after any accepted prefix.

## 3. Typed command inventory

| ID | Byte | Direction / class | Target / aggregation | Request or event frame | Response contract | Mutated-state readback |
|---|---:|---|---|---|---|---|
| `microphone_on` | `0x0E` | phone request / mutation | selected leg, default right / single leg | exactly 2 bytes; payload byte at offset 1 is enable `0x01` | 2–200 bytes; byte 1 is `0xC9` or `0xCB` | unavailable |
| `microphone_data` | `0xF1` | glasses event / stream | right leg / stream append | exactly 202 bytes; 200-byte LC3 payload at offset 2 | not applicable | not applicable |
| `touch_and_assistant_event` | `0xF5` | glasses event / control | originating leg / event dispatch | at least 2 bytes; event index at offset 1; optional vendor payload from offset 2 | not applicable | not applicable |
| `display_text_and_ai` | `0x4E` | phone request / mutation | left then right / both legs required | 10–200 bytes; 9-byte header; 1–191 UTF-8 payload bytes | 2–200 bytes; byte 1 is `0xC9` or `0xCB` | unavailable |
| `bitmap_packet` | `0x15` | phone request / mutation | active leg / staged transfer | first 7–200, later 3–196; 1–194 bitmap bytes; at most 256 frames | native acceptance only | deferred CRC is not general state readback |
| `bitmap_finish` | `0x20` | phone request / mutation | active leg / staged transfer | exactly `[0x20,0x0D,0x0E]` | 2–200 bytes; byte 0 `0x20`, byte 1 `0xC9` | followed by CRC; not authoritative state readback |
| `bitmap_crc` | `0x16` | phone request / mutation | active leg / staged transfer | exactly 5 bytes; big-endian CRC32/XZ at offset 1 | 6–200 bytes; byte 0 `0x16`, byte 5 `0xC9` | terminal validation only |
| `heartbeat` | `0x25` | phone request / mutation | left then right / both legs required | exactly 6 bytes; length `0x0006`, type `0x04`, echoed sequence | 6–200 bytes; byte 0 `0x25`, byte 4 `0x04` | liveness response only |
| `exit_mode` | `0x18` | phone request / mutation | left then right / both legs required | exactly one byte `[0x18]`; zero payload | 2–200 bytes; byte 1 is `0xC9` or `0xCB` | unavailable |
| `notification_whitelist` | `0x04` | phone request / mutation | left leg / fragmented | 4–180 bytes; 3-byte header; 1–177 UTF-8 JSON bytes; at most 255 frames | 2–200 bytes; byte 1 is `0xC9` or `0xCB` | unavailable |
| `notification` | `0x4B` | phone request / mutation | left leg / fragmented | 5–180 bytes; 4-byte header; 1–176 UTF-8 JSON bytes; at most 255 frames | 2–200 bytes; byte 0 `0x4B`, byte 1 `0xC9` or `0xCB` | unavailable |
| `serial_number_read` | `0x34` | phone request / query | selected leg / single leg | exactly one byte `[0x34]`; zero payload | 18–200 bytes; exactly 16 identity bytes at offsets 2–17 | query response only |

The typed minimum payload of one byte on fragmented producer profiles reflects the executable examples and the current public producer entry points. A future intentional empty-payload profile is a contract change and requires new source examples, tests and review rather than inheriting permission from a generic packet helper.

## 4. Platform initialization and audio framing

Android readiness is ordered as:

```text
gatt connected
-> services and characteristics discovered
-> notification descriptor accepted
-> MTU at least 203
-> [0xF4,0x01] initialization write accepted
```

iOS readiness is ordered as:

```text
peripheral connected
-> services and characteristics discovered
-> notifications enabled
-> [0x4D,0x01] initialization write enqueued
```

The platform-specific initialization bytes remain subject to vendor confirmation. The source bindings separately require Android and iOS to accept only 202-byte microphone events, remove the two-byte envelope, decode 200 LC3 bytes and produce 3,200 PCM bytes. Stale generation/attempt callbacks cannot publish into a current session.

## 5. Effect and retry semantics

For a mutating command:

| Window | Required result |
|---|---|
| authority/readiness rejection before native acceptance | no effect; retry only after obtaining fresh current authority and within an explicit budget |
| timeout after possible native acceptance | indeterminate; effect may have occurred |
| malformed response after possible write | indeterminate |
| negative response after write | command-specific failure requiring reconciliation |
| accepted fragment followed by failure | partial/indeterminate transfer; no blind restart |
| one leg succeeds and the other does not | degraded or indeterminate pair effect |

The contract intentionally grants no generic automatic replay after a possible write. Manual retry requires authoritative reconciliation or retirement of the exact generation before entering a new authority namespace. Serial-number read does not claim a mutation, but incomplete or malformed identity bytes are never published.

## 6. Golden vectors and predicates

The validator executes every producer and consumer vector against its typed profile. Important fixed vectors include:

```text
microphone enable  [0x0E,0x01]
bitmap finish      [0x20,0x0D,0x0E]
exit               [0x18]
serial query       [0x34]
```

Display position is signed 16-bit big-endian at offsets 5–6. Heartbeat byte 5 equals byte 3. Bitmap CRC response success is accepted only at byte 5. Expanding a zero-payload one-byte command, moving a payload offset, weakening an ACK predicate or transferring the explicitly unbounded `0xF5` vendor payload exception to the fixed LC3 frame fails.

## 7. Exact source bindings

Nine closed source bindings connect the machine profile to the current implementation:

1. Android readiness, MTU, initialization and LC3 framing;
2. bitmap packet/address/finish/CRC production and response handling;
3. BLE request correlation and assistant-event dispatch;
4. BLE timeout/quarantine disposition;
5. display packet header and big-endian position;
6. iOS initialization and LC3/PCM framing;
7. protocol command producers and fragmentation bounds;
8. effect aggregation and uncertainty state machine;
9. command-specific response predicates.

Each binding fixes its path and required implementation fragments. A path swap that preserves the binding count still fails, as does removing a single required fragment. All named test files must be regular repository files without symlink traversal.

## 8. Change protocol

A command/profile change must update, in one reviewed subject:

1. the typed JSON profile and its golden vectors;
2. producer and consumer source;
3. response/effect and retry tests;
4. exact source-binding fragments;
5. this document and compatibility notes;
6. the profile and whole-matrix canonical digests in the stable validator entry point;
7. all seven canonical exact-head jobs.

Changing a digest without independently comparing the complete typed profile, source and tests is not acceptance. The digest is an anti-drift lock, not a substitute for review.

## 9. Evidence ceiling

This source contract does not establish:

- vendor command meaning, firmware-version compatibility or an authoritative general state-readback protocol;
- RF loss, callback timing, physical latency, audio quality, power, thermal or soak behavior;
- secure boot, OTA, recovery, rollback, firmware signing or revocation authority;
- production Android ASR tenancy or platform privacy compliance;
- release-binary signing, store review, pilot or rollout qualification.

Those facts require the named vendor, physical lab, provider, platform, assurance and release authorities. Repository CI cannot manufacture them.
