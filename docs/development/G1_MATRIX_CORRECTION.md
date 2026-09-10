# G1 schema-v2 LC3 golden-vector correction

Status: exact source-contract repair; no vendor, physical, deployment or release claim.

## Subject

The schema-v2 matrix at `contracts/g1-command-matrix-v1.json` is pinned by canonical JSON SHA-256
`900deb5e601bcce7a6ac0241d3e4bab37dce8659a6d40f9fb3bfa4e47e9fec17`.
Its `microphone_data/lc3_frame` example contains 203 bytes: command `0xF1`, sequence `0x00`, and 201 zero fixture bytes. Android and iOS source both require a 202-byte event containing exactly 200 compressed LC3 payload bytes.

## Closed correction

`contracts/g1-command-matrix-v1-corrections.json` authorizes exactly one operation:

1. select command `microphone_data`;
2. select `consumer_examples` entry `lc3_frame`;
3. require the exact 203-byte zero-filled base fixture and exact base matrix digest;
4. delete one trailing zero;
5. require a 202-byte result with command, sequence and 200-byte payload.

The facade `services/qualification/g1_command_matrix.py` applies this operation before invoking the unchanged closed-shape validator implementation. It derives the effective whole-contract and microphone profile digests from the exact base-plus-correction pair. Every other profile retains its independently pinned digest.

The correction fails closed if the base matrix, selector, original length, prefix, payload contents, operation count, operation parameters or result length changes. It does not silently normalize arbitrary examples.

## Regression surface

`services/qualification/test_g1_matrix_correction.py` proves:

- the raw base is exactly the pinned 203-byte fixture;
- the effective contract is exactly 202 bytes with 200 LC3 payload bytes;
- already-short, non-zero-tail and altered correction subjects fail before application;
- a mutation after correction remains visible to the typed profile validator.

The existing `test_g1_command_matrix.py` suite then re-runs all command identity, wire-bound, effect, retry, readback, source-fragment and golden-vector hostile cases against the effective document.

## Claim ceiling

This is a source fixture correction only. It does not change production code or establish vendor protocol truth, firmware compatibility, physical audio quality, latency, power, thermal behavior, privacy behavior, general state readback, secure boot, OTA, rollback, binary signing, pilot, store approval or release qualification.
