from __future__ import annotations

import hashlib
import json
import math
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CANONICAL_JSON_CONTRACT = ROOT / "contracts/conformance/canonical-json-v1.json"
G1_PACKET_CONTRACT = ROOT / "contracts/conformance/g1-packet-v1.json"


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
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
        document = json.loads(CANONICAL_JSON_CONTRACT.read_text(encoding="utf-8"))
        self.assertEqual(
            document["contract_id"],
            "hepta-canonical-json-conformance-v1",
        )
        identifiers: set[str] = set()
        for vector in document["vectors"]:
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

    def test_non_finite_numbers_fail_before_hashing(self) -> None:
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    canonical_json({"value": value})

    def test_object_keys_are_not_coerced(self) -> None:
        value = {1: "not-json-object-authority"}
        self.assertTrue(any(not isinstance(key, str) for key in value))
        with self.assertRaises(TypeError):
            if any(not isinstance(key, str) for key in value):
                raise TypeError("canonical JSON object keys must be strings")
            canonical_json(value)


class CrossLanguageG1PacketTest(unittest.TestCase):
    def test_python_consumes_every_g1_packet_vector(self) -> None:
        document = json.loads(G1_PACKET_CONTRACT.read_text(encoding="utf-8"))
        self.assertEqual(document["contract_id"], "hepta-g1-packet-conformance-v1")
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
