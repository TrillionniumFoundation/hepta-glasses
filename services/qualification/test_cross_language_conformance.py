from __future__ import annotations

import hashlib
import json
import math
import unittest

from services.qualification.cross_language_json_reference import (
    CANONICAL_JSON_CONTRACT,
    ContractError,
    canonical_json,
    strict_json_file,
    strict_json_loads,
)
from services.qualification.g1_packet_reference import (
    G1_PACKET_CONTRACT,
    _GENERATED,
    _Lcg,
    _expect_error,
    _hex,
    _hex_list,
    _integer,
    _run_generated_case,
    fragment_packet as reference_fragment_packet,
    load_packet_contract,
    reassemble_packet as reference_reassemble_packet,
)

def _byte(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 255:
        raise ValueError(f"{name} must be a byte")
    return value


def fragment_packet(
    *, command: int, payload: bytes, max_packet_bytes: int, metadata: bytes = b""
) -> list[bytes]:
    _byte(command, "command")
    if isinstance(max_packet_bytes, bool) or not isinstance(max_packet_bytes, int):
        raise ValueError("max_packet_bytes must be an integer")
    header_bytes = 3 + len(metadata)
    if max_packet_bytes <= header_bytes:
        raise ValueError("max_packet_bytes leaves no payload room")
    chunk_bytes = max_packet_bytes - header_bytes
    frame_count = 1 if not payload else (len(payload) + chunk_bytes - 1) // chunk_bytes
    if frame_count > 255:
        raise ValueError("payload requires more than 255 frames")
    return [
        bytes((command, frame_count, sequence))
        + metadata
        + payload[sequence * chunk_bytes : (sequence + 1) * chunk_bytes]
        for sequence in range(frame_count)
    ]


def reassemble_packet(
    frames: list[bytes], *, expected_command: int | None, metadata_length: int
) -> bytes:
    if not frames:
        raise ValueError("at least one frame is required")
    if isinstance(metadata_length, bool) or not isinstance(metadata_length, int):
        raise ValueError("metadata_length must be an integer")
    if metadata_length < 0:
        raise ValueError("metadata_length must be non-negative")
    header_bytes = 3 + metadata_length
    first = frames[0]
    if len(first) < header_bytes:
        raise ValueError("short frame")
    command, total = first[0], first[1]
    metadata = first[3:header_bytes]
    if total == 0 or total != len(frames):
        raise ValueError("frame count mismatch")
    if expected_command is not None and command != expected_command:
        raise ValueError("unexpected command")
    ordered: list[bytes | None] = [None] * total
    for frame in frames:
        if (
            len(frame) < header_bytes
            or frame[0] != command
            or frame[1] != total
            or frame[3:header_bytes] != metadata
        ):
            raise ValueError("inconsistent frame binding")
        sequence = frame[2]
        if sequence >= total or ordered[sequence] is not None:
            raise ValueError("invalid sequence")
        ordered[sequence] = frame
    if any(frame is None for frame in ordered):
        raise ValueError("missing sequence")
    return b"".join(frame[header_bytes:] for frame in ordered if frame is not None)


class CrossLanguageCanonicalJsonTest(unittest.TestCase):
    def test_python_consumes_every_committed_vector(self) -> None:
        document = strict_json_file(CANONICAL_JSON_CONTRACT)
        self.assertIsInstance(document, dict)
        self.assertEqual(
            document["contract_id"],
            "hepta-canonical-json-conformance-v1",
        )
        vectors = document["vectors"]
        self.assertIsInstance(vectors, list)
        identifiers: set[str] = set()
        for vector in vectors:
            with self.subTest(vector=vector["id"]):
                self.assertNotIn(vector["id"], identifiers)
                identifiers.add(vector["id"])
                encoded = canonical_json(vector["value"])
                self.assertEqual(encoded, vector["canonical"])
                self.assertEqual(
                    hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
                    vector["sha256"],
                )
        self.assertGreaterEqual(len(identifiers), 6)

    def test_non_finite_numbers_and_non_string_keys_fail(self) -> None:
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    canonical_json({"value": value})
        with self.assertRaises(TypeError):
            canonical_json({1: "not-json-object-authority"})

    def test_strict_loader_rejects_duplicate_members(self) -> None:
        for source in (
            '{"id":"a","id":"b"}',
            '{"outer":{"id":"a","id":"b"}}',
            '{"value":NaN}',
        ):
            with self.subTest(source=source):
                with self.assertRaises(ContractError):
                    strict_json_loads(source)


class CrossLanguageG1PacketTest(unittest.TestCase):
    def test_contract_is_closed_and_every_positive_vector_matches(self) -> None:
        document = load_packet_contract()
        for vector in document["vectors"]:
            with self.subTest(vector=vector["id"]):
                command = _integer(
                    vector["command"], "command", 0, 255
                )
                maximum = _integer(
                    vector["max_packet_bytes"],
                    "max_packet_bytes",
                    4,
                    255,
                )
                metadata = _hex(
                    vector["metadata_hex"], "metadata_hex"
                )
                payload = _hex(
                    vector["payload_hex"], "payload_hex"
                )
                expected_frames = _hex_list(
                    vector["frames_hex"], "frames_hex"
                )
                frames = reference_fragment_packet(
                    command=command,
                    payload=payload,
                    max_packet_bytes=maximum,
                    metadata=metadata,
                )
                self.assertEqual(frames, expected_frames)
                self.assertEqual(
                    reference_reassemble_packet(
                        list(reversed(frames)),
                        expected_command=command,
                        metadata_length=len(metadata),
                    ),
                    payload,
                )

    def test_every_fixed_negative_vector_hits_exact_branch(self) -> None:
        document = load_packet_contract()
        for vector in document["negative_vectors"]:
            with self.subTest(vector=vector["id"]):
                frames = _hex_list(
                    vector["frames_hex"],
                    "negative frames_hex",
                    allow_empty=True,
                )
                metadata_length = _integer(
                    vector["metadata_length"],
                    "metadata_length",
                    0,
                    252,
                )
                expected_command = vector["expected_command"]
                if expected_command is not None:
                    expected_command = _integer(
                        expected_command,
                        "expected_command",
                        0,
                        255,
                    )
                expected_error = vector["expected_error"]
                self.assertIsInstance(expected_error, str)
                _expect_error(
                    lambda: reference_reassemble_packet(
                        frames,
                        expected_command=expected_command,
                        metadata_length=metadata_length,
                    ),
                    expected_error,
                )

    def test_all_generated_families_execute_exact_case_counts(self) -> None:
        document = load_packet_contract()
        executed = 0
        for family in document["generated_families"]:
            random = _Lcg(family["seed"])
            for _ in range(family["cases"]):
                _run_generated_case(family["id"], random)
                executed += 1
        self.assertEqual(
            executed,
            sum(cases for _, cases in _GENERATED.values()),
        )
        self.assertEqual(executed, 512)

    def test_duplicate_sequence_vector_has_same_cardinality(self) -> None:
        document = load_packet_contract()
        vector = next(
            item
            for item in document["negative_vectors"]
            if item["id"] == "duplicate-sequence-same-cardinality"
        )
        frames = [bytes.fromhex(value) for value in vector["frames_hex"]]
        self.assertEqual(len(frames), frames[0][1])
        sequences = [frame[2] for frame in frames]
        self.assertEqual(len(sequences), 3)
        self.assertEqual(sequences.count(1), 2)
        self.assertNotIn(2, sequences)
        _expect_error(
            lambda: reference_reassemble_packet(
                frames,
                expected_command=None,
                metadata_length=0,
            ),
            "Duplicate frame sequence.",
        )

    def test_contract_parser_rejects_unknown_fields_and_duplicate_ids(self) -> None:
        document = json.loads(G1_PACKET_CONTRACT.read_text(encoding="utf-8"))

        unknown = json.loads(json.dumps(document))
        unknown["unexpected"] = True
        with self.assertRaises(ContractError):
            load_packet_contract(json.dumps(unknown))

        duplicated = json.loads(json.dumps(document))
        duplicated["negative_vectors"][1]["id"] = duplicated[
            "negative_vectors"
        ][0]["id"]
        with self.assertRaises(ContractError):
            load_packet_contract(json.dumps(duplicated))

        source = G1_PACKET_CONTRACT.read_text(encoding="utf-8")
        duplicate_member = source.replace(
            '"schema_version": 2,',
            '"schema_version": 2, "schema_version": 2,',
            1,
        )
        with self.assertRaises(ContractError):
            load_packet_contract(duplicate_member)


class CrossLanguageG1PacketGoldenTest(unittest.TestCase):
    def test_python_consumes_every_g1_packet_vector(self) -> None:
        document = json.loads(G1_PACKET_CONTRACT.read_text(encoding="utf-8"))
        self.assertEqual(document["contract_id"], "hepta-g1-packet-conformance-v2")
        self.assertEqual(
            document["header"],
            {
                "command_offset": 0,
                "frame_count_offset": 1,
                "sequence_offset": 2,
                "fixed_bytes": 3,
            },
        )
        identifiers: set[str] = set()
        for vector in document["vectors"]:
            with self.subTest(vector=vector["id"]):
                self.assertNotIn(vector["id"], identifiers)
                identifiers.add(vector["id"])
                metadata = bytes.fromhex(vector["metadata_hex"])
                payload = bytes.fromhex(vector["payload_hex"])
                frames = fragment_packet(
                    command=vector["command"],
                    payload=payload,
                    max_packet_bytes=vector["max_packet_bytes"],
                    metadata=metadata,
                )
                self.assertEqual(
                    [frame.hex() for frame in frames],
                    vector["frames_hex"],
                )
                self.assertEqual(
                    reassemble_packet(
                        list(reversed(frames)),
                        expected_command=vector["command"],
                        metadata_length=len(metadata),
                    ),
                    payload,
                )
        self.assertGreaterEqual(len(identifiers), 4)

    def test_python_reference_rejects_metadata_drift(self) -> None:
        frames = fragment_packet(
            command=78,
            payload=bytes(range(12)),
            max_packet_bytes=8,
            metadata=b"\x07\x09",
        )
        malformed = list(frames)
        changed = bytearray(malformed[-1])
        changed[3] ^= 1
        malformed[-1] = bytes(changed)
        with self.assertRaises(ValueError):
            reassemble_packet(
                malformed,
                expected_command=78,
                metadata_length=2,
            )


if __name__ == "__main__":
    unittest.main()
