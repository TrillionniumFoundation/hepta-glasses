# G1 packet conformance, deterministic fuzzing and bounded mutation gate

Status: repository-controlled protocol test depth. This document does not claim vendor firmware conformance, physical Even G1 qualification or release readiness.

## Shared golden authority

`contracts/conformance/g1-packet-golden-v1.json` is the single checked-in vector set consumed by two independent implementations:

- `services/qualification/test_g1_packet_conformance.py` implements a small Python reference fragmenter/reassembler without importing production Dart code;
- `test/runtime/g1_packet_conformance_test.dart` drives the production `PacketCodec` implementation.

The contract uses a closed JSON shape, unique kebab-case vector IDs, canonical lowercase hexadecimal payloads/frames and explicit reassembly permutations. Vectors bind heartbeat, notification, display/assistant and microphone-data command bytes to `contracts/g1-ble-protocol-v1.json`, exercise empty and single-frame messages, metadata-aware fragmentation, out-of-order reassembly, the 191-byte display payload and two 200-byte LC3 chunks.

Golden agreement is a repository-source fact only. The command and size values still require vendor-firmware and physical-device evidence before E5–E7 maturity can be asserted.

## Deterministic property sweeps

The Python lane runs 2,048 fixed-seed cases. Each case varies command byte, metadata length/content, maximum packet size, payload size/content and frame ordering. It asserts byte-perfect round trip, at most 255 frames and no frame larger than the declared bound. A fixed aggregate digest makes a silent generator or random-sequence change review-visible.

The Dart lane runs a separate 512-case fixed-seed sweep against production code and checks the same safety properties. These sweeps are bounded deterministic regression tests, not an assertion of exhaustive state-space coverage.

## Fail-closed negative corpus

Both languages exercise rejection of:

- an empty frame list;
- duplicate sequence numbers;
- a missing sequence;
- an unexpected command;
- inconsistent frame totals;
- a frame shorter than its header;
- payloads requiring more than 255 frames.

The Python parser additionally rejects duplicate/non-finite JSON, open vector shapes, malformed bytes/hex, duplicate IDs and non-permutation reassembly orders.

## Bounded mutation testing

The Python test contains four deliberately incorrect protocol implementations:

- floor rather than ceiling frame count;
- one-based sequence numbers;
- omitted metadata;
- an oversized chunk calculation.

The shared vectors must kill every mutant. This is a narrow mutation gate for packet framing only; it is not whole-repository mutation coverage. Broader mutation testing, parser/state-machine fuzzing, HIL and provider integration remain separate roadmap items.

## Admission and maintenance

Any change to the source protocol contract, production `PacketCodec`, shared vectors or either consumer invalidates earlier CI/Artifact/review credit. The exact new head must pass all seven non-empty canonical jobs, produce an independently content-verified source Artifact and obtain a fresh eligible review. Do not weaken vectors to preserve a changed implementation, copy a prior Artifact, infer physical-device success from simulated bytes or administrator-bypass adoption.
