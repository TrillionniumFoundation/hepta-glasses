from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from services.qualification import g1_command_matrix as matrix

ROOT = Path(__file__).resolve().parents[2]


class G1CommandMatrixTests(unittest.TestCase):
    def document(self) -> dict[str, object]:
        return matrix.strict_json(ROOT / matrix.MATRIX)

    @staticmethod
    def command(document: dict[str, object], identifier: str) -> dict[str, object]:
        commands = document["commands"]
        assert isinstance(commands, list)
        value = next(
            item
            for item in commands
            if isinstance(item, dict) and item.get("id") == identifier
        )
        assert isinstance(value, dict)
        return value

    def test_complete_typed_matrix_matches_base_contract_and_source(self) -> None:
        result = matrix.validate(ROOT)
        self.assertIs(result["ok"], True)
        self.assertEqual(result["schema_version"], 2)
        self.assertEqual(result["commands"], 12)
        self.assertEqual(result["typed_profiles"], 12)
        self.assertEqual(result["mutating_commands"], 9)
        self.assertEqual(result["source_bindings"], 9)
        self.assertEqual(result["source_references"], 36)
        self.assertEqual(result["test_references"], 24)
        self.assertEqual(result["producer_examples"], 13)
        self.assertEqual(result["consumer_examples"], 14)
        self.assertIs(result["vendor_confirmation_required"], True)
        self.assertIs(result["physical_qualification_required"], True)

    def test_fixed_audio_notification_requires_att_mtu_205(self) -> None:
        document = self.document()
        android = next(
            item
            for item in document["platform_initialization"]
            if item["platform"] == "android"
        )
        self.assertIn("mtu_at_least_205", android["admission_steps"])
        base_contract = matrix.strict_json(ROOT / matrix.BASE_CONTRACT)
        self.assertEqual(
            base_contract["transport"]["android_minimum_ready_mtu"],
            205,
        )
        self.assertNotIn(
            "mtu_at_least_203",
            base_contract["readiness"]["android"],
        )

    def test_duplicate_command_byte_fails_closed(self) -> None:
        document = copy.deepcopy(self.document())
        first = self.command(document, "microphone_on")
        second = self.command(document, "microphone_data")
        second["command"] = first["command"]
        with self.assertRaisesRegex(
            matrix.G1CommandMatrixError,
            "duplicate command byte",
        ):
            matrix.validate_document(ROOT, document)

    def test_count_preserving_direction_swap_fails_closed(self) -> None:
        document = copy.deepcopy(self.document())
        request = self.command(document, "microphone_on")
        event = self.command(document, "microphone_data")
        request["direction"], event["direction"] = (
            event["direction"],
            request["direction"],
        )
        with self.assertRaisesRegex(
            matrix.G1CommandMatrixError,
            "wrong direction|typed command profile drifted",
        ):
            matrix.validate_document(ROOT, document)

    def test_count_preserving_effect_swap_fails_closed(self) -> None:
        document = copy.deepcopy(self.document())
        microphone = self.command(document, "microphone_on")
        serial = self.command(document, "serial_number_read")
        microphone["effect"], serial["effect"] = (
            copy.deepcopy(serial["effect"]),
            copy.deepcopy(microphone["effect"]),
        )
        with self.assertRaisesRegex(
            matrix.G1CommandMatrixError,
            "typed command profile drifted",
        ):
            matrix.validate_document(ROOT, document)

    def test_long_unsafe_retry_text_cannot_satisfy_typed_enum(self) -> None:
        document = copy.deepcopy(self.document())
        command = self.command(document, "microphone_on")
        effect = command["effect"]
        assert isinstance(effect, dict)
        effect["automatic_retry"] = (
            "retry_pre_write_post_write_timeout_negative_ack_and_malformed_"
            "response_because_this_string_is_long_but_unsafe"
        )
        with self.assertRaisesRegex(
            matrix.G1CommandMatrixError,
            "typed command profile drifted",
        ):
            matrix.validate_document(ROOT, document)

    def test_ack_predicate_offset_drift_fails_closed(self) -> None:
        document = copy.deepcopy(self.document())
        command = self.command(document, "notification")
        response = command["response"]
        assert isinstance(response, dict)
        checks = response["checks"]
        assert isinstance(checks, list)
        status = checks[1]
        assert isinstance(status, dict)
        status["offset"] = 0
        with self.assertRaisesRegex(
            matrix.G1CommandMatrixError,
            "violates response predicate|typed command profile drifted",
        ):
            matrix.validate_document(ROOT, document)

    def test_whitelist_bounds_cannot_drift_together(self) -> None:
        document = copy.deepcopy(self.document())
        command = self.command(document, "notification_whitelist")
        frame = command["frame"]
        assert isinstance(frame, dict)
        frame["first_frame_max_bytes"] = 181
        frame["subsequent_frame_max_bytes"] = 181
        frame["payload_max_bytes"] = 178
        frame["maximum_frames"] = 256
        with self.assertRaisesRegex(
            matrix.G1CommandMatrixError,
            "typed command profile drifted",
        ):
            matrix.validate_document(ROOT, document)

    def test_notification_header_offset_drift_fails_closed(self) -> None:
        document = copy.deepcopy(self.document())
        command = self.command(document, "notification")
        frame = command["frame"]
        assert isinstance(frame, dict)
        fields = frame["fields"]
        assert isinstance(fields, list)
        payload = next(
            field
            for field in fields
            if isinstance(field, dict) and field.get("name") == "utf8_json_payload"
        )
        assert isinstance(payload, dict)
        payload["offset_first"] = 3
        with self.assertRaisesRegex(
            matrix.G1CommandMatrixError,
            "typed command profile drifted",
        ):
            matrix.validate_document(ROOT, document)

    def test_display_big_endian_position_offset_drift_fails_closed(self) -> None:
        document = copy.deepcopy(self.document())
        command = self.command(document, "display_text_and_ai")
        frame = command["frame"]
        assert isinstance(frame, dict)
        fields = frame["fields"]
        assert isinstance(fields, list)
        position = next(
            field
            for field in fields
            if isinstance(field, dict) and field.get("name") == "position"
        )
        assert isinstance(position, dict)
        position["offset_first"] = 6
        position["offset_subsequent"] = 6
        with self.assertRaisesRegex(
            matrix.G1CommandMatrixError,
            "typed command profile drifted",
        ):
            matrix.validate_document(ROOT, document)

    def test_touch_event_unboundedness_is_explicit_and_non_transferable(self) -> None:
        document = copy.deepcopy(self.document())
        touch = self.command(document, "touch_and_assistant_event")
        audio = self.command(document, "microphone_data")
        touch_frame = touch["frame"]
        audio_frame = audio["frame"]
        assert isinstance(touch_frame, dict)
        assert isinstance(audio_frame, dict)
        audio_frame["first_frame_max_bytes"] = None
        audio_frame["unbounded_reason"] = touch_frame["unbounded_reason"]
        with self.assertRaisesRegex(
            matrix.G1CommandMatrixError,
            "typed command profile drifted",
        ):
            matrix.validate_document(ROOT, document)

    def test_zero_payload_one_byte_exit_vector_is_enforced(self) -> None:
        document = copy.deepcopy(self.document())
        command = self.command(document, "exit_mode")
        examples = command["producer_examples"]
        assert isinstance(examples, list)
        example = examples[0]
        assert isinstance(example, dict)
        example["bytes"] = [0x18, 0x00]
        with self.assertRaisesRegex(
            matrix.G1CommandMatrixError,
            "exceeds the typed frame maximum",
        ):
            matrix.validate_document(ROOT, document)

    def test_event_consumer_vector_minimum_is_enforced(self) -> None:
        document = copy.deepcopy(self.document())
        command = self.command(document, "touch_and_assistant_event")
        examples = command["consumer_examples"]
        assert isinstance(examples, list)
        example = examples[0]
        assert isinstance(example, dict)
        example["bytes"] = [0xF5]
        with self.assertRaisesRegex(
            matrix.G1CommandMatrixError,
            "shorter than the typed frame minimum",
        ):
            matrix.validate_document(ROOT, document)

    def test_response_golden_vector_predicate_is_enforced(self) -> None:
        document = copy.deepcopy(self.document())
        command = self.command(document, "bitmap_crc")
        examples = command["consumer_examples"]
        assert isinstance(examples, list)
        example = examples[0]
        assert isinstance(example, dict)
        example["bytes"] = [0x16, 0, 0, 0, 0, 0xCA]
        with self.assertRaisesRegex(
            matrix.G1CommandMatrixError,
            "violates response predicate",
        ):
            matrix.validate_document(ROOT, document)

    def test_readback_authority_cannot_be_promoted_by_boolean(self) -> None:
        document = copy.deepcopy(self.document())
        command = self.command(document, "bitmap_crc")
        readback = command["readback"]
        assert isinstance(readback, dict)
        readback["authoritative_for_mutated_state"] = True
        with self.assertRaisesRegex(
            matrix.G1CommandMatrixError,
            "typed command profile drifted",
        ):
            matrix.validate_document(ROOT, document)

    def test_source_binding_count_preserving_path_swap_fails_closed(self) -> None:
        document = copy.deepcopy(self.document())
        bindings = document["source_bindings"]
        assert isinstance(bindings, list)
        first = next(
            item
            for item in bindings
            if isinstance(item, dict) and item.get("id") == "proto-command-producers"
        )
        second = next(
            item
            for item in bindings
            if isinstance(item, dict) and item.get("id") == "display-packet-producer"
        )
        assert isinstance(first, dict)
        assert isinstance(second, dict)
        first["path"], second["path"] = second["path"], first["path"]
        with self.assertRaisesRegex(
            matrix.G1CommandMatrixError,
            "source fragment is absent|source binding",
        ):
            matrix.validate_document(ROOT, document)

    def test_missing_live_source_fragment_fails_closed(self) -> None:
        document = self.document()
        original = matrix.EXPECTED_SOURCE_BINDINGS
        altered = copy.deepcopy(original)
        altered["proto-command-producers"]["required_fragments"].append(
            "HEPTA_FRAGMENT_THAT_IS_DELIBERATELY_ABSENT"
        )
        with mock.patch.object(matrix, "EXPECTED_SOURCE_BINDINGS", altered):
            with self.assertRaisesRegex(
                matrix.G1CommandMatrixError,
                "source binding drifted|source fragment is absent",
            ):
                matrix.validate_document(ROOT, document)

    def test_unknown_typed_field_fails_closed(self) -> None:
        document = copy.deepcopy(self.document())
        command = self.command(document, "microphone_on")
        command["vendor_says_ok"] = True
        with self.assertRaisesRegex(
            matrix.G1CommandMatrixError,
            "shape mismatch",
        ):
            matrix.validate_document(ROOT, document)

    def test_duplicate_json_key_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.json"
            path.write_text(
                '{"schema_version":2,"schema_version":1}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                matrix.G1CommandMatrixError,
                "duplicate JSON key",
            ):
                matrix.strict_json(path)


if __name__ == "__main__":
    unittest.main()
