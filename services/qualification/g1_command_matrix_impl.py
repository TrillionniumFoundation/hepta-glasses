"""Validate the typed, closed G1 command/wire/effect matrix."""
from __future__ import annotations
import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping
ROOT = Path(__file__).resolve().parents[2]
MATRIX = Path('contracts/g1-command-matrix-v1.json')
BASE_CONTRACT = Path('contracts/g1-ble-protocol-v1.json')
HEX_BYTE = re.compile('^0x[0-9A-F]{2}$')
EXPECTED_MATRIX_SHA256 = '3142b741fb1ba9f94064a22c31e3cb0db5276b4aa47791f7951aa28b02b99450'
EXPECTED_COMMAND_IDENTITIES = {'bitmap_crc': {'aggregation': 'staged_single_leg_transfer', 'command': '0x16', 'direction': 'phone_to_glasses_request', 'operation_kind': 'mutating_command', 'target': 'active_bitmap_leg'}, 'bitmap_finish': {'aggregation': 'staged_single_leg_transfer', 'command': '0x20', 'direction': 'phone_to_glasses_request', 'operation_kind': 'mutating_command', 'target': 'active_bitmap_leg'}, 'bitmap_packet': {'aggregation': 'staged_single_leg_transfer', 'command': '0x15', 'direction': 'phone_to_glasses_request', 'operation_kind': 'mutating_command', 'target': 'active_bitmap_leg'}, 'display_text_and_ai': {'aggregation': 'pair_all_legs_required', 'command': '0x4E', 'direction': 'phone_to_glasses_request', 'operation_kind': 'mutating_command', 'target': 'pair_left_then_right'}, 'exit_mode': {'aggregation': 'pair_all_legs_required', 'command': '0x18', 'direction': 'phone_to_glasses_request', 'operation_kind': 'mutating_command', 'target': 'pair_left_then_right'}, 'heartbeat': {'aggregation': 'pair_all_legs_required', 'command': '0x25', 'direction': 'phone_to_glasses_request', 'operation_kind': 'mutating_command', 'target': 'pair_left_then_right'}, 'microphone_data': {'aggregation': 'stream_append', 'command': '0xF1', 'direction': 'glasses_to_phone_event', 'operation_kind': 'stream_event', 'target': 'right_leg_only'}, 'microphone_on': {'aggregation': 'single_leg', 'command': '0x0E', 'direction': 'phone_to_glasses_request', 'operation_kind': 'mutating_command', 'target': 'selected_leg_default_right'}, 'notification': {'aggregation': 'single_leg_fragmented', 'command': '0x4B', 'direction': 'phone_to_glasses_request', 'operation_kind': 'mutating_command', 'target': 'left_leg'}, 'notification_whitelist': {'aggregation': 'single_leg_fragmented', 'command': '0x04', 'direction': 'phone_to_glasses_request', 'operation_kind': 'mutating_command', 'target': 'left_leg'}, 'serial_number_read': {'aggregation': 'single_leg', 'command': '0x34', 'direction': 'phone_to_glasses_request', 'operation_kind': 'read_query', 'target': 'selected_leg'}, 'touch_and_assistant_event': {'aggregation': 'event_dispatch', 'command': '0xF5', 'direction': 'glasses_to_phone_event', 'operation_kind': 'control_event', 'target': 'originating_leg'}}
EXPECTED_PROFILE_SHA256 = {'bitmap_crc': 'a2b26241084d81b60505df7942ef3e24c2299ba0deb0fcbeb7a489c1df884b86', 'bitmap_finish': '58b62ed2f01d99cb68b4ceac66434b1590bf106fdfe355ffbceff5af50b82462', 'bitmap_packet': '6bdd4ee3d9e4a332948dd51bdf8a44286a9272038fb3157e97ca6fdd75bbdea9', 'display_text_and_ai': '6a54c270eb184a46d2be2c27ee4d8d67c3a1ec7a77313a1d33e7289dc8e0611d', 'exit_mode': '8f13708b834379524dc08ef94edbdef1844581912c741d3fd67a8844c5718ae8', 'heartbeat': 'f770f55d97d8cbb8361647203506b1e648bde3d59b9c1690a2af891fa4e073ea', 'microphone_data': 'e8b0db8625460a73de36d83588d502aadd26ebdcfa84fe1551f88779851c5f70', 'microphone_on': '6c5c136f1870f8298755d589db044b35313f0e2929bc40adb9aa9c2f6d487397', 'notification': '9016d6774f414f789c90d7a2cd2306c2be2cc2a66bc27b808d9dd2c06d4ecefe', 'notification_whitelist': '66586833d1a8be478407824c16a215b8555d5b2c9daa3ec8f0aefc00c9bc79cf', 'serial_number_read': '7ee42e7ad6e59e41bf29ced949b14a3a029bd60ae8fc31b185d6723c5a08bfc2', 'touch_and_assistant_event': 'c49638d59d9f00cc25b23ff32be85d55018f89ba9e1ece4cb0f4ffc63ba3ca36'}
EXPECTED_SOURCE_BINDINGS = {'android-audio-frame': {'path': 'android/app/src/main/kotlin/org/trillionnium/heptaglasses/bluetooth/BleManager.kt', 'required_fragments': ['const val REQUIRED_MTU = 205', 'private const val REQUESTED_MTU = 251', 'byteArrayOf(0xf4.toByte(), 0x01)', 'frame[0] == 0xF1.toByte()', 'side != "R" || frame.size != 202', 'frame.copyOfRange(2, 202)']}, 'bitmap-producer-consumer': {'path': 'lib/controllers/bmp_update_manager.dart', 'required_fragments': ['packetPayloadLength = 194', 'maximumPacketCount = 256', '<int>[0x00, 0x1c, 0x00, 0x00]', 'const <int>[0x20, 0x0d, 0x0e]', 'response.data.length >= 2', 'response.data[1] == 0xc9', 'response.data.length >= 6', 'response.data[5] == 0xc9', 'return DeviceEffectResult.indeterminate(']}, 'ble-correlation-and-events': {'path': 'lib/ble_manager.dart', 'required_fragments': ['if (command == 0xF5 && response.data.length > 1)', 'case 0:', 'case 1:', 'case 23:', 'case 24:', 'BleRequestKey(', 'generation: generation,', 'side: response.lr,', 'command: command,']}, 'ble-correlation-and-timeout': {'path': 'lib/ble_manager.dart', 'required_fragments': ["'ack_timeout_after_native_write'", 'effectMayHaveOccurred: true', 'response.effectMayHaveOccurred', "'retry_budget_exhausted_before_write'"]}, 'display-packet-producer': {'path': 'lib/services/evenai_proto.dart', 'required_fragments': ['int len = 191', 'byteData.setInt16(0, pos, Endian.big);', 'currentPageNumber,', 'maxPageNumber,']}, 'ios-audio-frame': {'path': 'ios/Runner/BluetoothManager.swift', 'required_fragments': ['Data([0x4d, 0x01])', 'guard data.count == 202 else { return }', 'data.subdata(in: 2..<data.count)', 'guard compressed.count == 200 else { return }', 'guard pcm.count == 3_200 else { return }']}, 'proto-command-producers': {'path': 'lib/services/proto.dart', 'required_fragments': ['Uint8List.fromList(<int>[0x0E, 0x01])', 'EvenaiProto.evenaiMultiPackListV2(', 'const length = 6;', 'Uint8List.fromList(<int>[0x18])', 'Uint8List.fromList(<int>[0x34])', 'count: 180,', 'const payloadBytes = 176;', 'if (packetCount > 255)']}, 'proto-effect-state-machine': {'path': 'lib/services/proto.dart', 'required_fragments': ['if (response.effectMayHaveOccurred) {', "'ack_missing_after_native_write'", 'if (response.isTimeout) {', "'request_rejected_before_write'", "'negative_or_malformed_ack_after_write'", "'dual_leg_partial_effect_indeterminate'", "'packet_sequence_partial_effect_indeterminate'"]}, 'proto-status-predicates': {'path': 'lib/services/proto.dart', 'required_fragments': ['data.length > 1 && (data[1] == 0xc9 || data[1] == 0xcb)', 'response.data.length > 5', 'response.data[0] == 0x25', 'response.data[4] == 0x04']}}
EXPECTED_SOURCE_BINDING_IDS = sorted(EXPECTED_SOURCE_BINDINGS)
BASE_COMMAND_KEYS = {'microphone_on': 'microphone', 'microphone_data': 'microphone_data', 'touch_and_assistant_event': 'touch_and_assistant_event', 'display_text_and_ai': 'display_text_and_ai', 'bitmap_packet': 'bitmap_packet', 'bitmap_finish': 'bitmap_finish', 'bitmap_crc': 'bitmap_crc', 'heartbeat': 'heartbeat', 'exit_mode': 'exit_mode', 'notification_whitelist': 'notification_whitelist', 'notification': 'notification'}
TOP_FIELDS = {'schema_version', 'contract_id', 'status', 'transport', 'platform_initialization', 'response_status', 'assistant_events', 'source_bindings', 'commands', 'cross_platform_invariants', 'external_gates'}
COMMAND_FIELDS = {'id', 'command', 'direction', 'operation_kind', 'target', 'aggregation', 'frame', 'response', 'effect', 'readback', 'source_binding_ids', 'tests', 'external_gates', 'producer_examples', 'consumer_examples'}
FRAME_FIELDS = {'kind', 'first_frame_min_bytes', 'first_frame_max_bytes', 'subsequent_frame_min_bytes', 'subsequent_frame_max_bytes', 'payload_offset_first', 'payload_offset_subsequent', 'payload_min_bytes', 'payload_max_bytes', 'payload_encoding', 'frame_count_kind', 'maximum_frames', 'unbounded_reason', 'fields'}
WIRE_FIELD_FIELDS = {'name', 'offset_first', 'offset_subsequent', 'width_bytes', 'encoding', 'constant', 'relation'}
RESPONSE_FIELDS = {'kind', 'minimum_bytes', 'maximum_bytes', 'checks', 'payload_offset', 'payload_bytes', 'event_index_offset', 'unbounded_reason'}
CHECK_FIELDS = {'kind', 'offset', 'values'}
EFFECT_FIELDS = {'pre_write_rejection', 'post_write_timeout', 'malformed_response', 'negative_response', 'partial_progress', 'automatic_retry', 'manual_retry'}
READBACK_FIELDS = {'kind', 'authoritative_for_mutated_state', 'scope'}
EXAMPLE_FIELDS = {'name', 'position', 'bytes'}
SOURCE_BINDING_FIELDS = {'id', 'path', 'required_fragments'}
REQUEST_DIRECTIONS = {'phone_to_glasses_request'}
EVENT_DIRECTIONS = {'glasses_to_phone_event'}
REQUEST_OPERATIONS = {'mutating_command', 'read_query'}
EVENT_OPERATIONS = {'stream_event', 'control_event'}
CHECK_KINDS = {'byte_equals', 'byte_in'}

class G1CommandMatrixError(ValueError):
    """Stable G1 command-matrix validation failure."""

def fail(message: str) -> None:
    raise G1CommandMatrixError(message)

def strict_json(path: Path) -> dict[str, Any]:

    def unique(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                fail(f'duplicate JSON key in {path}: {key}')
            result[key] = value
        return result
    try:
        value = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique, parse_constant=lambda value: fail(f'non-finite JSON number in {path}: {value}'))
    except G1CommandMatrixError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        fail(f'cannot parse {path}: {error}')
    if not isinstance(value, dict):
        fail(f'{path} must contain an object')
    return value

def canonical_digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(',', ':'), sort_keys=True).encode('utf-8')).hexdigest()

def closed_shape(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        fail(f'{label} shape mismatch: missing={sorted(expected - set(value))!r}, extra={sorted(set(value) - expected)!r}')

def string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        fail(f'{label} must be a non-empty string')
    return value

def integer_or_none(value: Any, label: str, minimum: int=0) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        fail(f'{label} must be null or an integer >= {minimum}')
    return value

def byte_list(value: Any, label: str, *, non_empty: bool=False) -> list[int]:
    if not isinstance(value, list) or (non_empty and (not value)):
        fail(f'{label} must be a byte list')
    result: list[int] = []
    for index, item in enumerate(value):
        if isinstance(item, bool) or not isinstance(item, int) or (not 0 <= item <= 255):
            fail(f'{label}[{index}] is not a byte')
        result.append(item)
    return result

def string_list(value: Any, label: str, *, non_empty: bool=True) -> list[str]:
    if not isinstance(value, list) or (non_empty and (not value)):
        fail(f'{label} must be a string list')
    result: list[str] = []
    for index, item in enumerate(value):
        text = string(item, f'{label}[{index}]')
        if text in result:
            fail(f'{label} contains duplicate {text!r}')
        result.append(text)
    return result

def repository_file(root: Path, value: Any, label: str) -> Path:
    relative = string(value, label)
    pure = PurePosixPath(relative)
    if pure.is_absolute() or '\\' in relative or (not pure.parts) or any((part in {'', '.', '..'} for part in relative.split('/'))):
        fail(f'{label} is not a canonical repository path: {relative}')
    path = root.joinpath(*pure.parts)
    if not path.is_file():
        fail(f'{label} does not identify a regular file: {relative}')
    current = root
    for component in path.relative_to(root).parts:
        current /= component
        if current.is_symlink():
            fail(f'{label} crosses a symbolic link: {relative}')
    return path

def command_map(document: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    commands = document.get('commands')
    if not isinstance(commands, list):
        fail('commands must be a list')
    result: dict[str, Mapping[str, Any]] = {}
    seen_bytes: set[str] = set()
    for index, command in enumerate(commands):
        if not isinstance(command, dict):
            fail(f'commands[{index}] must be an object')
        closed_shape(command, COMMAND_FIELDS, f'commands[{index}]')
        identifier = string(command['id'], f'commands[{index}].id')
        if identifier in result:
            fail(f'duplicate command id: {identifier}')
        command_byte = string(command['command'], f'{identifier}.command')
        if not HEX_BYTE.fullmatch(command_byte):
            fail(f'{identifier}.command is not canonical uppercase hex')
        if command_byte in seen_bytes:
            fail(f'duplicate command byte: {command_byte}')
        seen_bytes.add(command_byte)
        result[identifier] = command
    return result

def field_offset(field: Mapping[str, Any], position: str) -> int | None:
    return field['offset_first'] if position in {'first', 'event'} else field['offset_subsequent']

def frame_bounds(frame: Mapping[str, Any], position: str) -> tuple[int | None, int | None, int | None]:
    if position in {'first', 'event'}:
        return (frame['first_frame_min_bytes'], frame['first_frame_max_bytes'], frame['payload_offset_first'])
    if position == 'subsequent':
        return (frame['subsequent_frame_min_bytes'], frame['subsequent_frame_max_bytes'], frame['payload_offset_subsequent'])
    fail(f'invalid frame position: {position}')

def validate_frame_shape(frame: Mapping[str, Any], label: str) -> None:
    closed_shape(frame, FRAME_FIELDS, label)
    string(frame['kind'], f'{label}.kind')
    for name in ('first_frame_min_bytes', 'first_frame_max_bytes', 'subsequent_frame_min_bytes', 'subsequent_frame_max_bytes', 'payload_offset_first', 'payload_offset_subsequent', 'payload_min_bytes', 'payload_max_bytes', 'maximum_frames'):
        integer_or_none(frame[name], f'{label}.{name}')
    string(frame['payload_encoding'], f'{label}.payload_encoding')
    string(frame['frame_count_kind'], f'{label}.frame_count_kind')
    if frame['unbounded_reason'] is not None:
        string(frame['unbounded_reason'], f'{label}.unbounded_reason')
    fields = frame['fields']
    if not isinstance(fields, list) or not fields:
        fail(f'{label}.fields must be a non-empty list')
    names: set[str] = set()
    for index, field in enumerate(fields):
        if not isinstance(field, dict):
            fail(f'{label}.fields[{index}] must be an object')
        closed_shape(field, WIRE_FIELD_FIELDS, f'{label}.fields[{index}]')
        name = string(field['name'], f'{label}.fields[{index}].name')
        if name in names:
            fail(f'{label} has duplicate wire field {name}')
        names.add(name)
        integer_or_none(field['offset_first'], f'{label}.{name}.offset_first')
        integer_or_none(field['offset_subsequent'], f'{label}.{name}.offset_subsequent')
        integer_or_none(field['width_bytes'], f'{label}.{name}.width_bytes', 1)
        string(field['encoding'], f'{label}.{name}.encoding')
        if field['constant'] is not None:
            if isinstance(field['constant'], int):
                byte_list([field['constant']], f'{label}.{name}.constant')
            else:
                byte_list(field['constant'], f'{label}.{name}.constant', non_empty=True)
        if field['relation'] is not None:
            relation = string(field['relation'], f'{label}.{name}.relation')
            if not relation.startswith('equals:'):
                fail(f'{label}.{name} has an unsupported relation')

def validate_frame_example(frame: Mapping[str, Any], example: Mapping[str, Any], label: str) -> None:
    closed_shape(example, EXAMPLE_FIELDS, label)
    string(example['name'], f'{label}.name')
    position = string(example['position'], f'{label}.position')
    if position not in {'first', 'subsequent', 'event'}:
        fail(f'{label} has an invalid frame position')
    data = byte_list(example['bytes'], f'{label}.bytes', non_empty=True)
    minimum, maximum, payload_offset = frame_bounds(frame, position)
    if minimum is None:
        fail(f'{label} uses a non-applicable frame position')
    if len(data) < minimum:
        fail(f'{label} is shorter than the typed frame minimum')
    if maximum is not None and len(data) > maximum:
        fail(f'{label} exceeds the typed frame maximum')
    if maximum is None and (not frame['unbounded_reason']):
        fail(f'{label} has no maximum and no explicit reason')
    if payload_offset is not None:
        if payload_offset > len(data):
            fail(f'{label} payload offset exceeds the example')
        payload_length = len(data) - payload_offset
        minimum_payload = frame['payload_min_bytes']
        maximum_payload = frame['payload_max_bytes']
        if minimum_payload is not None and payload_length < minimum_payload:
            fail(f'{label} payload is shorter than the typed minimum')
        if maximum_payload is not None and payload_length > maximum_payload:
            fail(f'{label} payload exceeds the typed maximum')
    fields = frame['fields']
    by_name = {field['name']: field for field in fields}
    for field in fields:
        offset = field_offset(field, position)
        width = field['width_bytes']
        if offset is None or width is None:
            continue
        if offset + width > len(data):
            fail(f"{label} does not contain field {field['name']}")
        constant = field['constant']
        if constant is not None:
            expected = [constant] if isinstance(constant, int) else constant
            if data[offset:offset + width] != expected:
                fail(f"{label} violates constant field {field['name']}")
        relation = field['relation']
        if relation is not None:
            related_name = relation.removeprefix('equals:')
            related = by_name.get(related_name)
            if related is None:
                fail(f'{label} has an unknown related field')
            related_offset = field_offset(related, position)
            if related_offset is None or related['width_bytes'] != width:
                fail(f'{label} has an unresolvable field relation')
            if data[offset:offset + width] != data[related_offset:related_offset + width]:
                fail(f'{label} violates field relation {relation}')

def validate_response_shape(response: Mapping[str, Any], label: str) -> None:
    closed_shape(response, RESPONSE_FIELDS, label)
    string(response['kind'], f'{label}.kind')
    for name in ('minimum_bytes', 'maximum_bytes', 'payload_offset', 'payload_bytes', 'event_index_offset'):
        integer_or_none(response[name], f'{label}.{name}')
    if response['unbounded_reason'] is not None:
        string(response['unbounded_reason'], f'{label}.unbounded_reason')
    checks = response['checks']
    if not isinstance(checks, list):
        fail(f'{label}.checks must be a list')
    for index, check in enumerate(checks):
        if not isinstance(check, dict):
            fail(f'{label}.checks[{index}] must be an object')
        closed_shape(check, CHECK_FIELDS, f'{label}.checks[{index}]')
        if check['kind'] not in CHECK_KINDS:
            fail(f'{label}.checks[{index}].kind is invalid')
        integer_or_none(check['offset'], f'{label}.checks[{index}].offset')
        byte_list(check['values'], f'{label}.checks[{index}].values', non_empty=True)

def validate_response_example(response: Mapping[str, Any], example: Mapping[str, Any], label: str) -> None:
    closed_shape(example, EXAMPLE_FIELDS, label)
    string(example['name'], f'{label}.name')
    if example['position'] != 'response':
        fail(f'{label} must be a response example')
    data = byte_list(example['bytes'], f'{label}.bytes', non_empty=True)
    minimum = response['minimum_bytes']
    maximum = response['maximum_bytes']
    if minimum is None:
        fail(f'{label} exists for a response-less profile')
    if len(data) < minimum:
        fail(f'{label} is shorter than the typed response minimum')
    if maximum is not None and len(data) > maximum:
        fail(f'{label} exceeds the typed response maximum')
    if maximum is None and (not response['unbounded_reason']):
        fail(f'{label} has no maximum and no explicit reason')
    for check in response['checks']:
        offset = check['offset']
        if offset >= len(data):
            fail(f'{label} lacks checked byte {offset}')
        if data[offset] not in check['values']:
            fail(f'{label} violates response predicate at byte {offset}')

def validate_command(command: Mapping[str, Any], label: str) -> None:
    direction = string(command['direction'], f'{label}.direction')
    operation = string(command['operation_kind'], f'{label}.operation_kind')
    if direction not in REQUEST_DIRECTIONS | EVENT_DIRECTIONS:
        fail(f'{label}.direction is not a closed enum')
    if operation not in REQUEST_OPERATIONS | EVENT_OPERATIONS:
        fail(f'{label}.operation_kind is not a closed enum')
    if operation in REQUEST_OPERATIONS and direction not in REQUEST_DIRECTIONS:
        fail(f'{label} request operation has the wrong direction')
    if operation in EVENT_OPERATIONS and direction not in EVENT_DIRECTIONS:
        fail(f'{label} event operation has the wrong direction')
    string(command['target'], f'{label}.target')
    string(command['aggregation'], f'{label}.aggregation')
    frame = command['frame']
    response = command['response']
    effect = command['effect']
    readback = command['readback']
    if not all((isinstance(value, dict) for value in (frame, response, effect, readback))):
        fail(f'{label} typed profiles must be objects')
    validate_frame_shape(frame, f'{label}.frame')
    validate_response_shape(response, f'{label}.response')
    closed_shape(effect, EFFECT_FIELDS, f'{label}.effect')
    for name in EFFECT_FIELDS:
        string(effect[name], f'{label}.effect.{name}')
    closed_shape(readback, READBACK_FIELDS, f'{label}.readback')
    string(readback['kind'], f'{label}.readback.kind')
    if not isinstance(readback['authoritative_for_mutated_state'], bool):
        fail(f'{label} readback authority must be boolean')
    string(readback['scope'], f'{label}.readback.scope')
    string_list(command['source_binding_ids'], f'{label}.source_binding_ids')
    string_list(command['tests'], f'{label}.tests')
    string_list(command['external_gates'], f'{label}.external_gates')
    producers = command['producer_examples']
    consumers = command['consumer_examples']
    if not isinstance(producers, list) or not isinstance(consumers, list):
        fail(f'{label} examples must be lists')
    if direction in REQUEST_DIRECTIONS:
        if not producers:
            fail(f'{label} lacks a producer golden example')
        for index, example in enumerate(producers):
            if not isinstance(example, dict):
                fail(f'{label}.producer_examples[{index}] must be an object')
            validate_frame_example(frame, example, f'{label}.producer_examples[{index}]')
        if response['kind'] not in {'native_acceptance_only', 'not_applicable_event'}:
            if not consumers:
                fail(f'{label} lacks a consumer response example')
            for index, example in enumerate(consumers):
                if not isinstance(example, dict):
                    fail(f'{label}.consumer_examples[{index}] must be an object')
                validate_response_example(response, example, f'{label}.consumer_examples[{index}]')
    else:
        if producers:
            fail(f'{label} event profile contains phone producer examples')
        if not consumers:
            fail(f'{label} event profile lacks a consumer example')
        for index, example in enumerate(consumers):
            if not isinstance(example, dict) or example.get('position') != 'event':
                fail(f'{label} event example has the wrong position')
            validate_frame_example(frame, example, f'{label}.consumer_examples[{index}]')

def validate_source_bindings(root: Path, value: Any) -> dict[str, Mapping[str, Any]]:
    if not isinstance(value, list):
        fail('source_bindings must be a list')
    result: dict[str, Mapping[str, Any]] = {}
    for index, binding in enumerate(value):
        if not isinstance(binding, dict):
            fail(f'source_bindings[{index}] must be an object')
        closed_shape(binding, SOURCE_BINDING_FIELDS, f'source_bindings[{index}]')
        identifier = string(binding['id'], f'source_bindings[{index}].id')
        if identifier in result:
            fail(f'duplicate source binding id: {identifier}')
        expected = EXPECTED_SOURCE_BINDINGS.get(identifier)
        if expected is None or binding != {'id': identifier, **expected}:
            fail(f'{identifier} source binding drifted')
        path = repository_file(root, binding['path'], f'{identifier}.path')
        fragments = string_list(binding['required_fragments'], f'{identifier}.required_fragments')
        source = path.read_text(encoding='utf-8')
        for fragment in fragments:
            if fragment not in source:
                fail(f'{identifier} source fragment is absent: {fragment!r}')
        result[identifier] = binding
    if sorted(result) != EXPECTED_SOURCE_BINDING_IDS:
        fail(f'source binding set drifted: {sorted(result)!r}')
    return result

def validate_document(root: Path, document: Mapping[str, Any]) -> dict[str, Any]:
    closed_shape(document, TOP_FIELDS, str(MATRIX))
    if document['schema_version'] != 2:
        fail('unsupported G1 command matrix schema')
    if document['contract_id'] != 'hepta-g1-command-matrix-v1':
        fail('G1 command matrix contract identity drifted')
    if document['status'] != 'source_contract_vendor_and_physical_confirmation_required':
        fail('G1 command matrix status overclaims or drifted')
    base = strict_json(root / BASE_CONTRACT)
    if base.get('contract_id') != 'hepta-g1-ble-protocol-v1' or base.get('version') != 2:
        fail('base G1 BLE contract identity/version drifted')
    transport = document['transport']
    if not isinstance(transport, dict):
        fail('transport must be an object')
    base_transport = base.get('transport')
    base_authority = base.get('authority')
    if not isinstance(base_transport, dict) or not isinstance(base_authority, dict):
        fail('base G1 transport/authority contract is malformed')
    for name in ('topology', 'service_uuid', 'phone_write_uuid', 'phone_notify_uuid'):
        if transport.get(name) != base_transport.get(name):
            fail(f'transport.{name} disagrees with base G1 contract')
    quarantine = base_authority.get('uncertain_write_quarantine')
    if not isinstance(quarantine, dict):
        fail('base G1 quarantine contract is malformed')
    if transport.get('request_owner') != quarantine.get('identity'):
        fail('request owner disagrees with base G1 contract')
    if transport.get('effect_authority') != base_authority.get('idempotency_identity'):
        fail('effect authority disagrees with base G1 contract')
    initializers = document['platform_initialization']
    if not isinstance(initializers, list) or len(initializers) != 2:
        fail('platform_initialization must contain Android and iOS')
    base_initialization = base.get('initialization_bytes')
    base_readiness = base.get('readiness')
    if not isinstance(base_initialization, dict) or not isinstance(base_readiness, dict):
        fail('base initialization/readiness contract is malformed')
    seen_platforms: set[str] = set()
    for index, record in enumerate(initializers):
        if not isinstance(record, dict):
            fail(f'platform_initialization[{index}] must be an object')
        platform = string(record.get('platform'), f'platform_initialization[{index}].platform')
        if platform not in {'android', 'ios'} or platform in seen_platforms:
            fail(f'invalid or duplicate initialization platform: {platform}')
        seen_platforms.add(platform)
        expected_bytes = [int(value, 16) for value in base_initialization[platform]]
        if record.get('bytes') != expected_bytes:
            fail(f'{platform} initialization bytes disagree with base contract')
        expected_steps = list(base_readiness[platform])
        ready_after = expected_steps.pop()
        if record.get('admission_steps') != expected_steps or record.get('ready_after') != ready_after:
            fail(f'{platform} readiness sequence disagrees with base contract')
    if document['response_status'] != base.get('response_status'):
        fail('response status map disagrees with base G1 contract')
    base_events = base.get('assistant_events')
    expected_events = [{'index': base_events['exit'], 'event': 'exit'}, {'index': base_events['manual_page'], 'event': 'manual_page_left_previous_right_next'}, {'index': base_events['start'], 'event': 'assistant_start'}, {'index': base_events['recording_complete'], 'event': 'recording_complete'}]
    if document['assistant_events'] != expected_events:
        fail('assistant events disagree with base G1 contract')
    bindings = validate_source_bindings(root, document['source_bindings'])
    commands = command_map(document)
    if set(commands) != set(EXPECTED_COMMAND_IDENTITIES):
        fail(f'G1 command set drifted: {sorted(commands)!r}')
    base_commands = base.get('commands')
    if not isinstance(base_commands, dict):
        fail('base command map is malformed')
    used_bindings: set[str] = set()
    test_references = 0
    source_references = 0
    for identifier, expected_identity in EXPECTED_COMMAND_IDENTITIES.items():
        command = commands[identifier]
        validate_command(command, identifier)
        identity = {name: command[name] for name in ('command', 'direction', 'operation_kind', 'target', 'aggregation')}
        if identity != expected_identity:
            fail(f'{identifier} typed command identity drifted')
        if canonical_digest(command) != EXPECTED_PROFILE_SHA256[identifier]:
            fail(f'{identifier} typed command profile drifted')
        base_key = BASE_COMMAND_KEYS.get(identifier)
        if base_key is not None and base_commands.get(base_key) != command['command']:
            fail(f'{identifier} command disagrees with base G1 contract')
        for binding_id in command['source_binding_ids']:
            if binding_id not in bindings:
                fail(f'{identifier} names an unknown source binding')
            used_bindings.add(binding_id)
        for test in command['tests']:
            repository_file(root, test, f'{identifier}.test')
        source_references += len(command['source_binding_ids'])
        test_references += len(command['tests'])
    used_bindings.update((record['source_binding_id'] for record in initializers))
    if used_bindings != set(bindings):
        fail('source binding coverage is incomplete')
    framing = base.get('framing')
    if not isinstance(framing, dict):
        fail('base framing contract is malformed')
    display = commands['display_text_and_ai']['frame']
    bitmap = commands['bitmap_packet']['frame']
    audio = commands['microphone_data']['frame']
    if display['payload_max_bytes'] != framing['display_payload_bytes'] or display['first_frame_max_bytes'] != 9 + framing['display_payload_bytes'] or bitmap['payload_max_bytes'] != framing['bitmap_payload_bytes'] or (bitmap['first_frame_max_bytes'] != 6 + framing['bitmap_payload_bytes']) or (audio['first_frame_min_bytes'] != framing['microphone_frame_bytes']) or (audio['first_frame_max_bytes'] != framing['microphone_frame_bytes']) or (audio['payload_max_bytes'] != framing['lc3_payload_bytes']):
        fail('typed command framing disagrees with base G1 contract')
    position = next((field for field in display['fields'] if field['name'] == 'position'))
    if position['encoding'] != 'i16_be' or framing.get('position_endian') != 'big':
        fail('display position endian disagrees with base G1 contract')
    if canonical_digest(document) != EXPECTED_MATRIX_SHA256:
        fail('typed G1 matrix canonical digest drifted')
    return {'ok': True, 'schema_version': 2, 'commands': len(commands), 'mutating_commands': sum((command['operation_kind'] == 'mutating_command' for command in commands.values())), 'typed_profiles': len(commands), 'source_bindings': len(bindings), 'source_references': source_references, 'test_references': test_references, 'producer_examples': sum((len(command['producer_examples']) for command in commands.values())), 'consumer_examples': sum((len(command['consumer_examples']) for command in commands.values())), 'vendor_confirmation_required': True, 'physical_qualification_required': True}

def validate(root: Path=ROOT) -> dict[str, Any]:
    root = root.resolve()
    return validate_document(root, strict_json(root / MATRIX))

def main() -> int:
    try:
        result = validate(ROOT)
    except (G1CommandMatrixError, KeyError, OSError, TypeError, ValueError) as error:
        print(json.dumps({'ok': False, 'error': str(error)}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0
if __name__ == '__main__':
    raise SystemExit(main())
