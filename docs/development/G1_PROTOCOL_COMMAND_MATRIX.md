# G1 typed command, wire, effect and readback matrix

Status: source contract; vendor semantics and physical qualification remain external.  
Machine contract: `contracts/g1-command-matrix-v1.json` (`schema_version=2`).  
Validator: `services/qualification/g1_command_matrix.py`.  
Regression: `services/qualification/test_g1_command_matrix.py`.

## 1. Why schema version 2 exists

The first draft used long prose fields for target, ACK, retry and readback. A sufficiently long but unsafe sentence could satisfy that validator, and several wire bounds were only checked for total count rather than by command identity. Schema version 2 removes that ambiguity.

Every command now has a closed, command-specific typed profile for:

- direction and operation class;
- target leg and pair aggregation;
- first/subsequent frame bounds;
- payload offsets, bounds and encoding;
- frame count representation and maximum;
- byte fields, widths, endianness, constants and relations;
- response minimum/maximum, byte predicates and payload offsets;
- pre-write, post-write, malformed, negative and partial-progress dispositions;
- automatic and manual retry authority;
- readback kind, scope and whether it is authoritative for mutated state;
- source bindings and producer/consumer golden examples.

The contract identity remains `hepta-g1-command-matrix-v1` because it has not yet been released as an external compatibility surface. The schema is explicitly versioned and the validator rejects schema 1.

## 2. Authority model

A phone-to-glasses request is owned by:

```text
(connection_generation, side, command)
```

Mutation authority is scoped by:

```text
(pair_identity,
 connection_generation,
 side,
 caller_idempotency_key,
 payload_sha256)
```

Both structures are compared to `contracts/g1-ble-protocol-v1.json`. Current source also proves that a native-accepted write followed by timeout enters quarantine and returns `effectMayHaveOccurred=true`; it is not translated into a retry-safe failure.

For pair commands, left success followed by right rejection or uncertainty is not pair success. For fragmented commands, any failure after an accepted packet is partial progress and cannot authorize a blind restart.

## 3. Exact command profiles

| ID | Byte | Operation / direction | Target / aggregation | Frame bytes | Payload bytes @ first offset | Response | Post-write timeout | Automatic retry | Readback |
|---|---:|---|---|---|---|---|---|---|---|
| `microphone_on` | `0x0E` | `mutating_command` / `phone_to_glasses_request` | `selected_leg_default_right` / `single_leg` | 2..2 | 0..0 @ None | correlated_status, min=2 | `indeterminate_reconciliation_required` | `none` | `none` |
| `microphone_data` | `0xF1` | `stream_event` / `glasses_to_phone_event` | `right_leg_only` / `stream_append` | 202..202 | 200..200 @ 2 | not_applicable_event, min=None | `not_applicable_event` | `none` | `event_payload` |
| `touch_and_assistant_event` | `0xF5` | `control_event` / `glasses_to_phone_event` | `originating_leg` / `event_dispatch` | 2..unbounded | 0..unbounded @ 2 | not_applicable_event, min=None | `not_applicable_event` | `none` | `event_payload` |
| `display_text_and_ai` | `0x4E` | `mutating_command` / `phone_to_glasses_request` | `pair_left_then_right` / `pair_all_legs_required` | 10..200 / next 10..200 | 1..191 @ 9 | correlated_status, min=2 | `indeterminate_reconciliation_required` | `none` | `none` |
| `bitmap_packet` | `0x15` | `mutating_command` / `phone_to_glasses_request` | `active_bitmap_leg` / `staged_single_leg_transfer` | 7..200 / next 3..196 | 1..194 @ 6 | native_acceptance_only, min=None | `not_applicable_no_protocol_ack` | `none` | `terminal_crc_after_finish_only` |
| `bitmap_finish` | `0x20` | `mutating_command` / `phone_to_glasses_request` | `active_bitmap_leg` / `staged_single_leg_transfer` | 3..3 | 0..0 @ None | correlated_status, min=2 | `indeterminate_reconciliation_required` | `none` | `terminal_crc_follows` |
| `bitmap_crc` | `0x16` | `mutating_command` / `phone_to_glasses_request` | `active_bitmap_leg` / `staged_single_leg_transfer` | 5..5 | 0..0 @ None | crc_status, min=6 | `indeterminate_reconciliation_required` | `none` | `protocol_terminal_validation_not_state_readback` |
| `heartbeat` | `0x25` | `mutating_command` / `phone_to_glasses_request` | `pair_left_then_right` / `pair_all_legs_required` | 6..6 | 0..0 @ None | heartbeat_liveness, min=6 | `indeterminate_reconciliation_required` | `pre_write_only_maximum_two_retries` | `correlated_liveness_response` |
| `exit_mode` | `0x18` | `mutating_command` / `phone_to_glasses_request` | `pair_left_then_right` / `pair_all_legs_required` | 1..1 | 0..0 @ None | correlated_status, min=2 | `indeterminate_reconciliation_required` | `none` | `none` |
| `notification_whitelist` | `0x04` | `mutating_command` / `phone_to_glasses_request` | `left_leg` / `single_leg_fragmented` | 3..180 / next 3..180 | 0..177 @ 3 | correlated_status, min=2 | `indeterminate_reconciliation_required` | `none` | `none` |
| `notification` | `0x4B` | `mutating_command` / `phone_to_glasses_request` | `left_leg` / `single_leg_fragmented` | 4..180 / next 4..180 | 0..176 @ 4 | correlated_status, min=2 | `indeterminate_reconciliation_required` | `none` | `none` |
| `serial_number_read` | `0x34` | `read_query` / `phone_to_glasses_request` | `selected_leg` / `single_leg` | 1..1 | 0..0 @ None | serial_identity, min=18 | `no_identity_returned_manual_new_attempt` | `none` | `query_response_vendor_semantics_unconfirmed` |

`unbounded` is permitted only where current source enforces a minimum but deliberately has no upper bound. Each such field carries a machine-readable `unbounded_reason`. In particular, the optional vendor payload on `0xF5` is not silently assigned an invented limit.

## 4. Wire rules

### 4.1 Fixed one-frame commands

- Microphone enable is exactly `[0x0E, 0x01]`.
- Bitmap finish is exactly `[0x20, 0x0D, 0x0E]`.
- Bitmap CRC is exactly five bytes: command plus a big-endian CRC32/XZ value.
- Heartbeat is exactly six bytes. Byte 1 is `0x06`, byte 2 is `0x00`, byte 4 is `0x04`, and byte 5 must equal the sequence at byte 3.
- Exit mode is the zero-payload one-byte frame `[0x18]`.
- Serial-number read is the zero-payload one-byte query `[0x34]`.

The validator executes golden examples for all of these forms. Expanding a one-byte zero-payload command to two bytes fails.

### 4.2 Display text

The display header is nine bytes:

| Offset | Field | Encoding |
|---:|---|---|
| 0 | command | `u8`, constant `0x4E` |
| 1 | sync sequence | `u8` |
| 2 | packet count | `u8` |
| 3 | packet sequence | `u8` |
| 4 | new-screen flag | `u8` |
| 5 | position | signed 16-bit big-endian |
| 7 | current page | `u8` |
| 8 | maximum page | `u8` |
| 9 | text payload | UTF-8, 1–191 bytes |

A frame is 10–200 bytes and the count is at most 255. The big-endian rule is compared to the base BLE contract and to the producer source.

### 4.3 Notification whitelist

The whitelist header is three bytes:

```text
[0x04, packet_count, packet_sequence]
```

The payload is 0–177 UTF-8 JSON bytes; each frame is 3–180 bytes; packet count is at most 255. These values are derived from `_getPackList(... count: 180)` and its three-byte header. The regression suite changes all three numbers together to 181/178/256 and requires rejection, preventing a coordinated drift from passing.

### 4.4 Notification

The notification header is four bytes:

```text
[0x4B, message_id, packet_count, packet_sequence]
```

The payload is 0–176 UTF-8 JSON bytes; each frame is 4–180 bytes; packet count is at most 255. The extra message ID means this profile cannot inherit the whitelist offsets by count alone.

### 4.5 Bitmap data

The first bitmap frame is:

```text
[0x15, sequence=0, 0x00, 0x1C, 0x00, 0x00, payload 1..194]
```

Subsequent frames are:

```text
[0x15, sequence, payload 1..194]
```

First-frame bounds are 7–200 bytes; subsequent-frame bounds are 3–196 bytes; sequences span 0–255, for at most 256 frames. Data packets use native write acceptance rather than a protocol ACK. Rejection before any accepted packet is pre-write; rejection after progress is indeterminate.

### 4.6 Inbound audio and assistant events

LC3 microphone data is exactly 202 bytes:

```text
[0xF1, packet_sequence, 200-byte LC3 payload]
```

Both Android and iOS source bindings enforce 202 input bytes, offset 2, 200 compressed bytes and 3,200 decoded PCM bytes. Current Android source accepts only the right leg for this stream.

Assistant events require at least `[0xF5, event_index]`. Indices 0, 1, 23 and 24 are bound to exit, manual page, assistant start and recording complete. Unknown indices are bounded metadata; stale or unscoped events are dropped.

## 5. Response and effect semantics

Generic status commands require a response correlated by generation, side and command, with status byte 1 in `(201, 203)`. Bitmap finish accepts only `0xC9` at byte 1. Bitmap CRC requires command `0x16` at byte 0 and `0xC9` at byte 5. Heartbeat requires command `0x25` and byte 4 equal to `0x04`. Serial identity requires at least 18 bytes and reads exactly bytes 2–17.

The typed effect state is intentionally conservative:

| Window | Mutating command |
|---|---|
| native rejection before acceptance | not applied; retry only after authority recheck |
| timeout after possible acceptance | indeterminate; reconciliation required |
| malformed response after write | indeterminate; reconciliation required |
| negative response after write | indeterminate under current source contract |
| accepted fragment followed by failure | partial/indeterminate; no blind restart |
| one pair leg succeeds and the other does not | degraded or indeterminate pair result |

Only heartbeat performs automatic retry, and only while the result remains explicitly pre-write/retry-safe, with at most two retries after the initial attempt. Serial read has no automatic retry; a caller may begin a bounded new read under the unchanged authority.

## 6. Source binding

The machine contract names nine closed source bindings. The validator reads the exact head and requires the implementation fragments that establish:

- command bytes and producer constants;
- display payload size and big-endian position;
- bitmap payload/count/address/finish/CRC behavior;
- request correlation, quarantine and timeout disposition;
- pair/fragment aggregation and partial-effect codes;
- Android/iOS initialization and LC3 frame sizes;
- assistant event dispatch.

Changing source without updating the corresponding profile, golden examples and qualification code fails. Changing only the prose does not change normative behavior.

## 7. Adversarial coverage

The regression suite rejects:

- duplicate command bytes;
- count-preserving direction swaps;
- count-preserving effect-policy swaps;
- long unsafe retry prose placed where a closed enum is required;
- ACK/status offset drift;
- coordinated whitelist 181/178/256 drift;
- notification payload-offset drift;
- display endian-field offset drift;
- transfer of the `0xF5` unbounded exception to LC3 audio;
- expansion of one-byte zero-payload commands;
- short event frames and invalid response vectors;
- readback authority promotion;
- count-preserving source-binding swaps;
- missing required implementation fragments;
- unknown fields and duplicate JSON keys.

## 8. External limits

This contract does not prove:

- vendor command meaning or firmware compatibility;
- an authoritative readback protocol for general mutated display/device state;
- physical RF loss, callback timing, latency, power, thermal or soak behavior;
- secure boot, OTA, recovery, rollback or firmware signing authority;
- Android production ASR quality or platform privacy compliance;
- release-binary or store qualification.

Those conclusions require the named vendor, lab, platform, assurance and release authorities. Source CI cannot manufacture them.
