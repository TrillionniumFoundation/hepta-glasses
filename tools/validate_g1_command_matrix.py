#!/usr/bin/env python3
"""Validate the closed G1 per-command protocol matrix."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]
MATRIX = Path("contracts/g1-command-matrix-v1.json")
BASE_CONTRACT = Path("contracts/g1-ble-protocol-v1.json")
HEX_BYTE = re.compile(r"^0x[0-9A-F]{2}$")

EXPECTED_COMMANDS = {
    "microphone_on": "0x0E",
    "microphone_data": "0xF1",
    "touch_and_assistant_event": "0xF5",
    "display_text_and_ai": "0x4E",
    "bitmap_packet": "0x15",
    "bitmap_finish": "0x20",
    "bitmap_crc": "0x16",
    "heartbeat": "0x25",
    "exit_mode": "0x18",
    "notification_whitelist": "0x04",
    "notification": "0x4B",
    "serial_number_read": "0x34",
}

BASE_COMMAND_KEYS = {
    "microphone_on": "microphone",
    "microphone_data": "microphone_data",
    "touch_and_assistant_event": "touch_and_assistant_event",
    "display_text_and_ai": "display_text_and_ai",
    "bitmap_packet": "bitmap_packet",
    "bitmap_finish": "bitmap_finish",
    "bitmap_crc": "bitmap_crc",
    "heartbeat": "heartbeat",
    "exit_mode": "exit_mode",
    "notification_whitelist": "notification_whitelist",
    "notification": "notification",
}

EXPECTED_INVARIANTS = {
    "pair_ready_requires_both_legs_ready",
    "positive_generation_and_non_placeholder_pair_identity_required_for_authoritative_response",
    "native_prewrite_rechecks_expected_generation_pair_and_side_readiness",
    "missing_ack_after_possible_write_is_indeterminate",
    "one_leg_success_is_not_pair_success",
    "opposite_leg_disconnect_does_not_release_uncertain_write_quarantine",
    "stale_generation_or_attempt_callbacks_cannot_publish_current_events",
    "source_contract_does_not_establish_vendor_or_physical_truth",
}

COMMAND_FIELDS = {
    "id",
    "command",
    "direction",
    "target",
    "mutation",
    "request_layout",
    "response_layout",
    "max_packet_bytes",
    "max_payload_bytes",
    "packet_count_max",
    "acknowledgement",
    "retry_semantics",
    "readback",
    "source_refs",
    "tests",
    "external_gates",
}


class G1CommandMatrixError(ValueError):
    """Stable G1 command matrix validation failure."""


def fail(message: str) -> None:
    raise G1CommandMatrixError(message)


def strict_json(path: Path) -> dict[str, Any]:
    def unique(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                fail(f"duplicate JSON key in {path}: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=unique,
            parse_constant=lambda value: fail(
                f"non-finite JSON number in {path}: {value}"
            ),
        )
    except G1CommandMatrixError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        fail(f"cannot parse {path}: {error}")
    if not isinstance(value, dict):
        fail(f"{path} must contain an object")
    return value


def closed_shape(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        fail(
            f"{label} shape mismatch: "
            f"missing={sorted(expected - set(value))!r}, "
            f"extra={sorted(set(value) - expected)!r}"
        )


def text(value: Any, label: str, minimum: int = 1) -> str:
    if not isinstance(value, str) or len(value.strip()) < minimum:
        fail(f"{label} must be a substantive string")
    return value.strip()


def string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        fail(f"{label} must be a non-empty list")
    result: list[str] = []
    for index, item in enumerate(value):
        item_text = text(item, f"{label}[{index}]")
        if item_text in result:
            fail(f"{label} contains duplicate {item_text!r}")
        result.append(item_text)
    return result


def optional_positive_int(value: Any, label: str, *, allow_zero: bool = False) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        fail(f"{label} must be an integer or null")
    minimum = 0 if allow_zero else 1
    if value < minimum:
        fail(f"{label} must be >= {minimum}")
    return value


def repository_file(root: Path, value: Any, label: str) -> str:
    relative = text(value, label)
    pure = PurePosixPath(relative)
    if (
        pure.is_absolute()
        or "\\" in relative
        or not pure.parts
        or any(part in {"", ".", ".."} for part in relative.split("/"))
    ):
        fail(f"{label} is not a canonical repository path: {relative}")
    path = root.joinpath(*pure.parts)
    if not path.is_file():
        fail(f"{label} does not identify a regular file: {relative}")
    current = root
    for component in path.relative_to(root).parts:
        current /= component
        if current.is_symlink():
            fail(f"{label} crosses a symbolic link: {relative}")
    return relative


def command_map(document: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    commands = document.get("commands")
    if not isinstance(commands, list):
        fail("commands must be a list")
    result: dict[str, Mapping[str, Any]] = {}
    seen_bytes: set[str] = set()
    for index, command in enumerate(commands):
        if not isinstance(command, dict):
            fail(f"commands[{index}] must be an object")
        closed_shape(command, COMMAND_FIELDS, f"commands[{index}]")
        identifier = text(command["id"], f"commands[{index}].id")
        if identifier in result:
            fail(f"duplicate command id: {identifier}")
        byte = text(command["command"], f"{identifier}.command")
        if not HEX_BYTE.fullmatch(byte):
            fail(f"{identifier}.command is not canonical uppercase hex")
        if byte in seen_bytes:
            fail(f"duplicate command byte: {byte}")
        seen_bytes.add(byte)
        result[identifier] = command
    return result


def validate_document(root: Path, document: Mapping[str, Any]) -> dict[str, Any]:
    closed_shape(
        document,
        {
            "schema_version",
            "contract_id",
            "status",
            "transport",
            "platform_initialization",
            "response_status",
            "assistant_events",
            "commands",
            "cross_platform_invariants",
            "external_gates",
        },
        str(MATRIX),
    )
    if document["schema_version"] != 1:
        fail("unsupported G1 command matrix schema")
    if document["contract_id"] != "hepta-g1-command-matrix-v1":
        fail("G1 command matrix contract identity drifted")
    if document["status"] != "source_contract_vendor_and_physical_confirmation_required":
        fail("G1 command matrix status overclaims or drifted")

    base = strict_json(root / BASE_CONTRACT)
    if base.get("contract_id") != "hepta-g1-ble-protocol-v1" or base.get("version") != 2:
        fail("base G1 BLE contract identity/version drifted")

    transport = document["transport"]
    if not isinstance(transport, dict):
        fail("transport must be an object")
    closed_shape(
        transport,
        {
            "topology",
            "service_uuid",
            "phone_write_uuid",
            "phone_notify_uuid",
            "request_owner",
            "effect_authority",
        },
        "transport",
    )
    base_transport = base.get("transport")
    if not isinstance(base_transport, dict):
        fail("base transport contract is malformed")
    for field in ("topology", "service_uuid", "phone_write_uuid", "phone_notify_uuid"):
        if transport[field] != base_transport.get(field):
            fail(f"transport.{field} disagrees with base G1 contract")
    for field in ("request_owner", "effect_authority"):
        text(transport[field], f"transport.{field}", 24)

    initializers = document["platform_initialization"]
    if not isinstance(initializers, list) or len(initializers) != 2:
        fail("platform_initialization must contain Android and iOS")
    observed_platforms: set[str] = set()
    base_initialization = base.get("initialization_bytes")
    if not isinstance(base_initialization, dict):
        fail("base initialization contract is malformed")
    for index, record in enumerate(initializers):
        if not isinstance(record, dict):
            fail(f"platform_initialization[{index}] must be an object")
        closed_shape(
            record,
            {
                "platform",
                "bytes",
                "admission",
                "ready_rule",
                "source_ref",
                "external_gate",
            },
            f"platform_initialization[{index}]",
        )
        platform = text(record["platform"], f"platform_initialization[{index}].platform")
        if platform not in {"android", "ios"} or platform in observed_platforms:
            fail(f"invalid or duplicate initialization platform: {platform}")
        observed_platforms.add(platform)
        expected_bytes = "[" + ",".join(base_initialization[platform]) + "]"
        if record["bytes"] != expected_bytes:
            fail(f"{platform} initialization bytes disagree with base contract")
        text(record["admission"], f"{platform}.admission", 20)
        text(record["ready_rule"], f"{platform}.ready_rule", 20)
        repository_file(root, record["source_ref"], f"{platform}.source_ref")
        text(record["external_gate"], f"{platform}.external_gate", 20)

    response_status = document["response_status"]
    if response_status != base.get("response_status"):
        fail("response status map disagrees with base G1 contract")

    assistant_events = document["assistant_events"]
    if not isinstance(assistant_events, dict):
        fail("assistant_events must be an object")
    expected_events = {
        str(value): key if key != "manual_page" else "manual_page_left_previous_right_next"
        for key, value in base.get("assistant_events", {}).items()
    }
    if assistant_events != expected_events:
        fail("assistant event map disagrees with base G1 contract")

    commands = command_map(document)
    if set(commands) != set(EXPECTED_COMMANDS):
        fail(f"G1 command set drifted: {sorted(commands)!r}")
    base_commands = base.get("commands")
    if not isinstance(base_commands, dict):
        fail("base command map is malformed")

    source_reference_count = 0
    test_reference_count = 0
    for identifier, expected_byte in EXPECTED_COMMANDS.items():
        command = commands[identifier]
        if command["command"] != expected_byte:
            fail(f"{identifier} command byte drifted")
        base_key = BASE_COMMAND_KEYS.get(identifier)
        if base_key is not None and base_commands.get(base_key) != expected_byte:
            fail(f"{identifier} disagrees with base G1 command map")
        if command["direction"] not in {"phone_to_glasses", "glasses_to_phone"}:
            fail(f"{identifier}.direction is invalid")
        text(command["target"], f"{identifier}.target", 8)
        if not isinstance(command["mutation"], bool):
            fail(f"{identifier}.mutation must be boolean")
        text(command["request_layout"], f"{identifier}.request_layout", 20)
        text(command["response_layout"], f"{identifier}.response_layout", 20)
        packet = optional_positive_int(command["max_packet_bytes"], f"{identifier}.max_packet_bytes")
        payload = optional_positive_int(
            command["max_payload_bytes"],
            f"{identifier}.max_payload_bytes",
            allow_zero=True,
        )
        optional_positive_int(command["packet_count_max"], f"{identifier}.packet_count_max")
        if packet is not None and payload is not None and payload > packet:
            fail(f"{identifier} payload exceeds packet bound")
        text(command["acknowledgement"], f"{identifier}.acknowledgement", 4)
        text(command["retry_semantics"], f"{identifier}.retry_semantics", 40)
        text(command["readback"], f"{identifier}.readback", 8)
        sources = string_list(command["source_refs"], f"{identifier}.source_refs")
        tests = string_list(command["tests"], f"{identifier}.tests")
        for source in sources:
            repository_file(root, source, f"{identifier}.source_ref")
        for test in tests:
            repository_file(root, test, f"{identifier}.test")
        gates = string_list(command["external_gates"], f"{identifier}.external_gates")
        for gate in gates:
            if len(gate) < 12:
                fail(f"{identifier} contains a non-substantive external gate")
        source_reference_count += len(sources)
        test_reference_count += len(tests)

    framing = base.get("framing")
    if not isinstance(framing, dict):
        fail("base framing contract is malformed")
    expected_framing = {
        "display_text_and_ai": (200, framing.get("display_payload_bytes")),
        "bitmap_packet": (200, framing.get("bitmap_payload_bytes")),
        "microphone_data": (framing.get("microphone_frame_bytes"), framing.get("lc3_payload_bytes")),
    }
    for identifier, (packet, payload) in expected_framing.items():
        if commands[identifier]["max_packet_bytes"] != packet:
            fail(f"{identifier} packet bound disagrees with base framing")
        if commands[identifier]["max_payload_bytes"] != payload:
            fail(f"{identifier} payload bound disagrees with base framing")

    invariants = set(string_list(document["cross_platform_invariants"], "cross_platform_invariants"))
    if invariants != EXPECTED_INVARIANTS:
        fail(f"cross-platform invariant set drifted: {sorted(invariants)!r}")
    external_gates = string_list(document["external_gates"], "external_gates")
    if len(external_gates) < 6:
        fail("aggregate external gate inventory is incomplete")

    return {
        "ok": True,
        "commands": len(commands),
        "mutating_commands": sum(bool(command["mutation"]) for command in commands.values()),
        "source_references": source_reference_count,
        "test_references": test_reference_count,
        "external_gates": len(external_gates),
        "vendor_confirmation_required": True,
        "physical_qualification_required": True,
    }


def validate(root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    return validate_document(root, strict_json(root / MATRIX))


def main() -> int:
    try:
        result = validate(ROOT)
    except (G1CommandMatrixError, KeyError, OSError, TypeError) as error:
        print(json.dumps({"ok": False, "error": str(error)}), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
