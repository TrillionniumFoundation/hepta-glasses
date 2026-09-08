from __future__ import annotations

import json
import math
import random
import re
import unittest
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
VECTORS = ROOT / "contracts/conformance/g1-packet-golden-v1.json"
PROTOCOL = ROOT / "contracts/g1-ble-protocol-v1.json"
HEX = re.compile(r"^(?:[0-9a-f]{2})*$")


def _closed_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON member: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON value: {value}")


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_closed_object,
        parse_constant=_reject_constant,
    )
    if not isinstance(value, dict):
        raise TypeError(f"{path.name} must contain an object")
    return value


def _byte(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 255:
        raise ValueError(f"{name} must be an integer byte")
    return value


def fragment(
    command: int,
    payload: bytes,
    *,
    max_packet_bytes: int,
    metadata: tuple[int, ...] = (),
) -> tuple[bytes, ...]:
    _byte(command, "command")
    for index, value in enumerate(metadata):
        _byte(value, f"metadata[{index}]")
    header_bytes = 3 + len(metadata)
    if (
        isinstance(max_packet_bytes, bool)
        or not isinstance(max_packet_bytes, int)
        or max_packet_bytes <= header_bytes
    ):
        raise ValueError("max_packet_bytes must leave payload capacity")
    chunk_bytes = max_packet_bytes - header_bytes
    frame_count = 1 if not payload else math.ceil(len(payload) / chunk_bytes)
    if frame_count > 255:
        raise OverflowError("payload requires more than 255 frames")
    return tuple(
        bytes(
            (
                command,
                frame_count,
                sequence,
                *metadata,
                *payload[
                    sequence * chunk_bytes : (sequence + 1) * chunk_bytes
                ],
            )
        )
        for sequence in range(frame_count)
    )


def reassemble(
    frames: tuple[bytes, ...],
    *,
    expected_command: int | None = None,
    metadata_length: int = 0,
) -> bytes:
    if not frames:
        raise ValueError("at least one frame is required")
    if (
        isinstance(metadata_length, bool)
        or not isinstance(metadata_length, int)
        or metadata_length < 0
    ):
        raise ValueError("metadata_length must be a non-negative integer")
    header_bytes = 3 + metadata_length
    if len(frames[0]) < header_bytes:
        raise ValueError("frame is shorter than its header")
    command = frames[0][0]
    total = frames[0][1]
    if total == 0 or total != len(frames):
        raise ValueError("frame count does not match header")
    if expected_command is not None and command != expected_command:
        raise ValueError("unexpected command")

    ordered: list[bytes | None] = [None] * total
    for frame in frames:
        if (
            len(frame) < header_bytes
            or frame[0] != command
            or frame[1] != total
        ):
            raise ValueError("inconsistent frame header")
        sequence = frame[2]
        if sequence >= total or ordered[sequence] is not None:
            raise ValueError("duplicate or invalid frame sequence")
        ordered[sequence] = frame
    if any(frame is None for frame in ordered):
        raise ValueError("missing frame sequence")
    return b"".join(frame[header_bytes:] for frame in ordered if frame is not None)


def _parse_vectors() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    document = _load(VECTORS)
    expected = {
        "schema_version",
        "contract_id",
        "source_contract",
        "codec",
        "vectors",
        "negative_cases",
    }
    if set(document) != expected:
        raise ValueError(
            f"golden contract fields differ: {sorted(set(document) ^ expected)}"
        )
    if document["schema_version"] != 1:
        raise ValueError("schema_version must be 1")
    if document["contract_id"] != "hepta-g1-packet-golden-v1":
        raise ValueError("unexpected contract_id")
    if document["source_contract"] != "contracts/g1-ble-protocol-v1.json":
        raise ValueError("unexpected source_contract")
    if document["codec"] != "lib/runtime/packet_codec.dart":
        raise ValueError("unexpected codec")
    vectors = document["vectors"]
    if not isinstance(vectors, list) or not vectors:
        raise ValueError("vectors must be a non-empty array")
    parsed: list[dict[str, Any]] = []
    ids: set[str] = set()
    vector_fields = {
        "id",
        "command",
        "max_packet_bytes",
        "metadata",
        "payload_hex",
        "frames_hex",
        "reassembly_order",
    }
    for vector in vectors:
        if not isinstance(vector, dict) or set(vector) != vector_fields:
            raise ValueError("vector uses an open or malformed shape")
        vector_id = vector["id"]
        if (
            not isinstance(vector_id, str)
            or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", vector_id)
            or vector_id in ids
        ):
            raise ValueError("vector id must be unique kebab-case")
        ids.add(vector_id)
        command = _byte(vector["command"], f"{vector_id}.command")
        max_packet_bytes = vector["max_packet_bytes"]
        if (
            isinstance(max_packet_bytes, bool)
            or not isinstance(max_packet_bytes, int)
            or max_packet_bytes < 4
            or max_packet_bytes > 65535
        ):
            raise ValueError(f"{vector_id}.max_packet_bytes is invalid")
        metadata_value = vector["metadata"]
        if not isinstance(metadata_value, list):
            raise ValueError(f"{vector_id}.metadata must be an array")
        metadata = tuple(
            _byte(value, f"{vector_id}.metadata[{index}]")
            for index, value in enumerate(metadata_value)
        )
        payload_hex = vector["payload_hex"]
        frames_hex = vector["frames_hex"]
        order = vector["reassembly_order"]
        if not isinstance(payload_hex, str) or not HEX.fullmatch(payload_hex):
            raise ValueError(f"{vector_id}.payload_hex is not lowercase hex")
        if (
            not isinstance(frames_hex, list)
            or not frames_hex
            or any(
                not isinstance(item, str) or not HEX.fullmatch(item)
                for item in frames_hex
            )
        ):
            raise ValueError(f"{vector_id}.frames_hex is invalid")
        if (
            not isinstance(order, list)
            or any(isinstance(item, bool) or not isinstance(item, int) for item in order)
            or sorted(order) != list(range(len(frames_hex)))
        ):
            raise ValueError(f"{vector_id}.reassembly_order is not a permutation")
        parsed.append(
            {
                "id": vector_id,
                "command": command,
                "max_packet_bytes": max_packet_bytes,
                "metadata": metadata,
                "payload": bytes.fromhex(payload_hex),
                "frames": tuple(bytes.fromhex(item) for item in frames_hex),
                "reassembly_order": tuple(order),
            }
        )
    return document, parsed


class G1PacketConformanceTests(unittest.TestCase):
    def test_protocol_contract_binds_golden_commands_and_sizes(self) -> None:
        _, vectors = _parse_vectors()
        protocol = _load(PROTOCOL)
        self.assertEqual(protocol["contract_id"], "hepta-g1-ble-protocol-v1")
        self.assertEqual(protocol["version"], 2)
        self.assertEqual(protocol["commands"]["heartbeat"], "0x25")
        self.assertEqual(protocol["commands"]["notification"], "0x4B")
        self.assertEqual(protocol["commands"]["display_text_and_ai"], "0x4E")
        self.assertEqual(protocol["commands"]["microphone_data"], "0xF1")
        self.assertEqual(protocol["framing"]["display_payload_bytes"], 191)
        self.assertEqual(protocol["framing"]["lc3_payload_bytes"], 200)
        by_id = {vector["id"]: vector for vector in vectors}
        self.assertEqual(by_id["empty-heartbeat"]["command"], 0x25)
        self.assertEqual(by_id["small-notification"]["command"], 0x4B)
        self.assertEqual(by_id["display-payload-191"]["command"], 0x4E)
        self.assertEqual(len(by_id["display-payload-191"]["payload"]), 191)
        self.assertEqual(by_id["lc3-two-frames"]["command"], 0xF1)
        self.assertEqual(
            by_id["lc3-two-frames"]["max_packet_bytes"] - 3,
            protocol["framing"]["lc3_payload_bytes"],
        )

    def test_reference_implementation_matches_every_golden_vector(self) -> None:
        _, vectors = _parse_vectors()
        for vector in vectors:
            with self.subTest(vector=vector["id"]):
                actual = fragment(
                    vector["command"],
                    vector["payload"],
                    max_packet_bytes=vector["max_packet_bytes"],
                    metadata=vector["metadata"],
                )
                self.assertEqual(actual, vector["frames"])
                shuffled = tuple(
                    actual[index] for index in vector["reassembly_order"]
                )
                self.assertEqual(
                    reassemble(
                        shuffled,
                        expected_command=vector["command"],
                        metadata_length=len(vector["metadata"]),
                    ),
                    vector["payload"],
                )

    def test_seeded_property_sweep_is_deterministic(self) -> None:
        rng = random.Random(0x4845505441)
        digest = __import__("hashlib").sha256()
        for case in range(2048):
            metadata = tuple(rng.randrange(256) for _ in range(rng.randrange(4)))
            max_packet_bytes = rng.randrange(4 + len(metadata), 204)
            capacity = max_packet_bytes - 3 - len(metadata)
            payload_length = rng.randrange(min(capacity * 32 + 1, 4097))
            payload = bytes(rng.randrange(256) for _ in range(payload_length))
            command = rng.randrange(256)
            frames = fragment(
                command,
                payload,
                max_packet_bytes=max_packet_bytes,
                metadata=metadata,
            )
            order = list(range(len(frames)))
            rng.shuffle(order)
            rebuilt = reassemble(
                tuple(frames[index] for index in order),
                expected_command=command,
                metadata_length=len(metadata),
            )
            self.assertEqual(rebuilt, payload, case)
            self.assertLessEqual(len(frames), 255)
            self.assertTrue(all(len(frame) <= max_packet_bytes for frame in frames))
            for frame in frames:
                digest.update(frame)
        self.assertEqual(
            digest.hexdigest(),
            "7468b93e72c04e26298517fb516b169a708151d2b32794fbad3dd3b9095dfcea",
        )

    def test_hostile_frame_mutations_fail_closed(self) -> None:
        _, vectors = _parse_vectors()
        vector = next(item for item in vectors if item["id"] == "multi-frame-text")
        frames = list(vector["frames"])
        cases: dict[str, tuple[tuple[bytes, ...], int | None]] = {
            "duplicate-sequence": (
                (
                    frames[0],
                    bytes([frames[1][0], frames[1][1], 0]) + frames[1][3:],
                    frames[2],
                ),
                vector["command"],
            ),
            "missing-sequence": ((frames[0], frames[2]), vector["command"]),
            "wrong-command": (tuple(frames), 0xFF),
            "inconsistent-total": (
                (
                    bytes([frames[0][0], 2, frames[0][2]]) + frames[0][3:],
                    *frames[1:],
                ),
                vector["command"],
            ),
            "short-header": ((b"\x4e\x01",), vector["command"]),
        }
        for name, (candidate, expected_command) in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    reassemble(
                        candidate,
                        expected_command=expected_command,
                    )
        with self.assertRaises(ValueError):
            reassemble(())
        with self.assertRaises(OverflowError):
            fragment(0x15, b"\x00" * 256, max_packet_bytes=4)

    def test_bounded_mutation_gate_kills_every_protocol_mutant(self) -> None:
        _, vectors = _parse_vectors()

        def floor_count(vector: dict[str, Any]) -> tuple[bytes, ...]:
            header = 3 + len(vector["metadata"])
            chunk = vector["max_packet_bytes"] - header
            count = (
                1
                if not vector["payload"]
                else max(1, len(vector["payload"]) // chunk)
            )
            return tuple(
                bytes(
                    (
                        vector["command"],
                        count,
                        sequence,
                        *vector["metadata"],
                        *vector["payload"][
                            sequence * chunk : (sequence + 1) * chunk
                        ],
                    )
                )
                for sequence in range(count)
            )

        def one_based_sequence(vector: dict[str, Any]) -> tuple[bytes, ...]:
            good = fragment(
                vector["command"],
                vector["payload"],
                max_packet_bytes=vector["max_packet_bytes"],
                metadata=vector["metadata"],
            )
            return tuple(
                bytes([frame[0], frame[1], (frame[2] + 1) & 0xFF]) + frame[3:]
                for frame in good
            )

        def omit_metadata(vector: dict[str, Any]) -> tuple[bytes, ...]:
            return fragment(
                vector["command"],
                vector["payload"],
                max_packet_bytes=vector["max_packet_bytes"],
                metadata=(),
            )

        def oversized_chunk(vector: dict[str, Any]) -> tuple[bytes, ...]:
            return fragment(
                vector["command"],
                vector["payload"],
                max_packet_bytes=vector["max_packet_bytes"] + 1,
                metadata=vector["metadata"],
            )

        mutants: dict[str, Callable[[dict[str, Any]], tuple[bytes, ...]]] = {
            "floor-frame-count": floor_count,
            "one-based-sequence": one_based_sequence,
            "omit-metadata": omit_metadata,
            "oversized-chunk": oversized_chunk,
        }
        survivors: list[str] = []
        for name, mutant in mutants.items():
            killed = False
            for vector in vectors:
                try:
                    if mutant(vector) != vector["frames"]:
                        killed = True
                        break
                except (OverflowError, ValueError):
                    killed = True
                    break
            if not killed:
                survivors.append(name)
        self.assertEqual(survivors, [])


if __name__ == "__main__":
    unittest.main()
