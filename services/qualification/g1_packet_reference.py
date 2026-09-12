from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from services.qualification.cross_language_json_reference import (
    ROOT,
    ContractError,
    _closed_object,
    _exact_ids,
    _hex,
    _hex_list,
    _integer,
    strict_json_file,
    strict_json_loads,
)

G1_PACKET_CONTRACT = ROOT / "contracts/conformance/g1-packet-v1.json"

_PACKET_TOP_FIELDS = {
    "contract_id",
    "schema_version",
    "header",
    "vectors",
    "negative_vectors",
    "generated_families",
}
_PACKET_HEADER_FIELDS = {
    "command_offset",
    "frame_count_offset",
    "sequence_offset",
    "fixed_bytes",
}
_POSITIVE_VECTOR_FIELDS = {
    "id",
    "command",
    "max_packet_bytes",
    "metadata_hex",
    "payload_hex",
    "frames_hex",
}
_NEGATIVE_VECTOR_FIELDS = {
    "id",
    "frames_hex",
    "metadata_length",
    "expected_command",
    "expected_error",
}
_GENERATED_FAMILY_FIELDS = {"id", "seed", "cases"}

_POSITIVE_IDS = [
    "empty-payload",
    "single-frame-with-metadata",
    "five-binary-frames",
    "utf8-is-opaque-bytes",
]
_NEGATIVE_IDS = [
    "empty-frame-set",
    "short-first-frame",
    "zero-declared-frame-count",
    "declared-count-does-not-match-cardinality",
    "expected-command-mismatch",
    "inconsistent-frame-command",
    "inconsistent-frame-total",
    "inconsistent-metadata",
    "sequence-outside-range-same-cardinality",
    "duplicate-sequence-same-cardinality",
]
_GENERATED = {
    "round-trip": (12648430, 128),
    "zero-declared-frame-count": (60417409, 64),
    "sequence-outside-range-same-cardinality": (2882343476, 64),
    "duplicate-sequence-same-cardinality": (3735928559, 64),
    "metadata-drift": (195936478, 64),
    "command-drift": (4277009102, 64),
    "total-drift": (305419896, 64),
}

def _byte(value: object, name: str) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value <= 255
    ):
        raise ValueError(f"{name} must be a byte")
    return value


def fragment_packet(
    *,
    command: int,
    payload: bytes,
    max_packet_bytes: int,
    metadata: bytes = b"",
) -> list[bytes]:
    _byte(command, "command")
    for index, value in enumerate(metadata):
        _byte(value, f"metadata[{index}]")
    if isinstance(max_packet_bytes, bool) or not isinstance(
        max_packet_bytes, int
    ):
        raise ValueError("max_packet_bytes must be an integer")
    header_bytes = 3 + len(metadata)
    if max_packet_bytes <= header_bytes:
        raise ValueError("max_packet_bytes leaves no payload room")
    chunk_bytes = max_packet_bytes - header_bytes
    frame_count = (
        1
        if not payload
        else (len(payload) + chunk_bytes - 1) // chunk_bytes
    )
    if frame_count > 255:
        raise ValueError("payload requires more than 255 frames")
    return [
        bytes((command, frame_count, sequence))
        + metadata
        + payload[
            sequence * chunk_bytes : (sequence + 1) * chunk_bytes
        ]
        for sequence in range(frame_count)
    ]


def reassemble_packet(
    frames: list[bytes],
    *,
    expected_command: int | None,
    metadata_length: int,
) -> bytes:
    if not frames:
        raise ContractError("At least one frame is required.")
    if (
        isinstance(metadata_length, bool)
        or not isinstance(metadata_length, int)
        or metadata_length < 0
    ):
        raise ValueError("metadata_length must be a non-negative integer")
    header_bytes = 3 + metadata_length
    first = frames[0]
    if len(first) < header_bytes:
        raise ContractError("Frame is shorter than its header.")
    command, total = first[0], first[1]
    if total == 0 or total != len(frames):
        raise ContractError("Frame count does not match header.")
    if expected_command is not None and command != expected_command:
        raise ContractError("Unexpected command.")

    metadata = first[3:header_bytes]
    ordered: list[bytes | None] = [None] * total
    for frame in frames:
        if (
            len(frame) < header_bytes
            or frame[0] != command
            or frame[1] != total
        ):
            raise ContractError("Inconsistent frame header.")
        if frame[3:header_bytes] != metadata:
            raise ContractError("Inconsistent frame metadata.")
        sequence = frame[2]
        if sequence >= total:
            raise ContractError("Frame sequence is outside declared range.")
        if ordered[sequence] is not None:
            raise ContractError("Duplicate frame sequence.")
        ordered[sequence] = frame
    if any(frame is None for frame in ordered):
        raise ContractError("Missing frame sequence.")
    return b"".join(
        frame[header_bytes:]
        for frame in ordered
        if frame is not None
    )


def load_packet_contract(source: str | None = None) -> dict[str, Any]:
    root = strict_json_file(G1_PACKET_CONTRACT) if source is None else strict_json_loads(source)
    root = _closed_object(root, _PACKET_TOP_FIELDS, "packet contract")
    if (
        root["contract_id"] != "hepta-g1-packet-conformance-v2"
        or root["schema_version"] != 2
    ):
        raise ContractError("unexpected packet contract identity")
    header = _closed_object(root["header"], _PACKET_HEADER_FIELDS, "header")
    if header != {
        "command_offset": 0,
        "frame_count_offset": 1,
        "sequence_offset": 2,
        "fixed_bytes": 3,
    }:
        raise ContractError("packet header contract drift")

    vectors = root["vectors"]
    negatives = root["negative_vectors"]
    families = root["generated_families"]
    if not isinstance(vectors, list) or not isinstance(negatives, list) or not isinstance(families, list):
        raise ContractError("packet vector collections must be arrays")

    normalized_vectors = [
        _closed_object(value, _POSITIVE_VECTOR_FIELDS, "positive vector")
        for value in vectors
    ]
    normalized_negatives = [
        _closed_object(value, _NEGATIVE_VECTOR_FIELDS, "negative vector")
        for value in negatives
    ]
    normalized_families = [
        _closed_object(value, _GENERATED_FAMILY_FIELDS, "generated family")
        for value in families
    ]
    _exact_ids(normalized_vectors, _POSITIVE_IDS, "positive vectors")
    _exact_ids(normalized_negatives, _NEGATIVE_IDS, "negative vectors")
    _exact_ids(
        normalized_families,
        list(_GENERATED),
        "generated families",
    )
    for family in normalized_families:
        expected = _GENERATED[family["id"]]
        if (
            _integer(family["seed"], "generated seed", 0, 0xFFFFFFFF)
            != expected[0]
            or _integer(family["cases"], "generated cases", 1, 4096)
            != expected[1]
        ):
            raise ContractError(
                f"generated family drift: {family['id']}"
            )
    return root


class _Lcg:
    def __init__(self, seed: int) -> None:
        self.state = seed

    def next_int(self, upper_bound: int) -> int:
        if upper_bound <= 0:
            raise ValueError("upper_bound must be positive")
        self.state = (
            1664525 * self.state + 1013904223
        ) & 0xFFFFFFFF
        return self.state % upper_bound

    def bytes(self, length: int) -> bytes:
        return bytes(self.next_int(256) for _ in range(length))


def _frame(
    *,
    command: int,
    total: int,
    sequence: int,
    metadata: bytes,
    payload_byte: int,
) -> bytes:
    return bytes(
        (command, total, sequence, *metadata, payload_byte)
    )


def _expect_error(
    operation: Callable[[], object],
    expected: str,
) -> None:
    try:
        operation()
    except ContractError as exc:
        if str(exc) != expected:
            raise AssertionError(
                f"expected {expected!r}, observed {str(exc)!r}"
            ) from exc
        return
    raise AssertionError(f"operation did not raise {expected!r}")


def _run_generated_case(
    family: str,
    random: _Lcg,
) -> None:
    if family == "round-trip":
        metadata = random.bytes(random.next_int(4))
        payload = random.bytes(random.next_int(129))
        max_packet_bytes = 4 + len(metadata) + random.next_int(20)
        command = random.next_int(256)
        frames = fragment_packet(
            command=command,
            payload=payload,
            max_packet_bytes=max_packet_bytes,
            metadata=metadata,
        )
        observed = reassemble_packet(
            list(reversed(frames)),
            expected_command=command,
            metadata_length=len(metadata),
        )
        if observed != payload:
            raise AssertionError("round-trip payload drift")
        return

    if family == "zero-declared-frame-count":
        metadata = random.bytes(random.next_int(4))
        frame = bytes(
            (
                random.next_int(256),
                0,
                0,
                *metadata,
                random.next_int(256),
            )
        )
        _expect_error(
            lambda: reassemble_packet(
                [frame],
                expected_command=None,
                metadata_length=len(metadata),
            ),
            "Frame count does not match header.",
        )
        return

    if family == "sequence-outside-range-same-cardinality":
        total = 2 + random.next_int(4)
        metadata = random.bytes(random.next_int(4))
        frames = [
            _frame(
                command=78,
                total=total,
                sequence=sequence,
                metadata=metadata,
                payload_byte=random.next_int(256),
            )
            for sequence in range(total - 1)
        ]
        frames.append(
            _frame(
                command=78,
                total=total,
                sequence=total,
                metadata=metadata,
                payload_byte=random.next_int(256),
            )
        )
        if len(frames) != total:
            raise AssertionError("outside-range family changed cardinality")
        _expect_error(
            lambda: reassemble_packet(
                frames,
                expected_command=None,
                metadata_length=len(metadata),
            ),
            "Frame sequence is outside declared range.",
        )
        return

    if family == "duplicate-sequence-same-cardinality":
        total = 3 + random.next_int(3)
        metadata = random.bytes(random.next_int(4))
        frames = [
            _frame(
                command=78,
                total=total,
                sequence=sequence,
                metadata=metadata,
                payload_byte=random.next_int(256),
            )
            for sequence in range(total - 1)
        ]
        frames.append(
            _frame(
                command=78,
                total=total,
                sequence=total - 2,
                metadata=metadata,
                payload_byte=random.next_int(256),
            )
        )
        if len(frames) != total:
            raise AssertionError("duplicate family changed cardinality")
        _expect_error(
            lambda: reassemble_packet(
                frames,
                expected_command=None,
                metadata_length=len(metadata),
            ),
            "Duplicate frame sequence.",
        )
        return

    if family == "metadata-drift":
        metadata = bytearray(random.bytes(1 + random.next_int(3)))
        changed = bytearray(metadata)
        changed[0] ^= 1
        frames = [
            _frame(
                command=78,
                total=2,
                sequence=0,
                metadata=bytes(metadata),
                payload_byte=random.next_int(256),
            ),
            _frame(
                command=78,
                total=2,
                sequence=1,
                metadata=bytes(changed),
                payload_byte=random.next_int(256),
            ),
        ]
        _expect_error(
            lambda: reassemble_packet(
                frames,
                expected_command=None,
                metadata_length=len(metadata),
            ),
            "Inconsistent frame metadata.",
        )
        return

    if family == "command-drift":
        frames = [
            _frame(
                command=78,
                total=2,
                sequence=0,
                metadata=b"",
                payload_byte=random.next_int(256),
            ),
            _frame(
                command=79,
                total=2,
                sequence=1,
                metadata=b"",
                payload_byte=random.next_int(256),
            ),
        ]
        _expect_error(
            lambda: reassemble_packet(
                frames,
                expected_command=None,
                metadata_length=0,
            ),
            "Inconsistent frame header.",
        )
        return

    if family == "total-drift":
        frames = [
            _frame(
                command=78,
                total=2,
                sequence=0,
                metadata=b"",
                payload_byte=random.next_int(256),
            ),
            _frame(
                command=78,
                total=3,
                sequence=1,
                metadata=b"",
                payload_byte=random.next_int(256),
            ),
        ]
        _expect_error(
            lambda: reassemble_packet(
                frames,
                expected_command=None,
                metadata_length=0,
            ),
            "Inconsistent frame header.",
        )
        return

    raise ContractError(f"unknown generated family: {family}")


