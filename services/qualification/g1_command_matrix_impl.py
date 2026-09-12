"""Validate the typed, closed G1 command/wire/effect matrix."""
from __future__ import annotations
import hashlib
import json
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping
ROOT = Path(__file__).resolve().parents[2]
MATRIX = Path('contracts/g1-command-matrix-v1.json')
BASE_CONTRACT = Path('contracts/g1-ble-protocol-v1.json')
HEX_BYTE = re.compile('^0x[0-9A-F]{2}$')
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
SOURCE_BINDING_FIELDS = {'id', 'path', 'blob_sha256', 'scopes'}
SOURCE_SCOPE_FIELDS = {'kind', 'name', 'checks'}
SOURCE_CHECK_FIELDS = {'id', 'tokens', 'occurrences'}
TEST_REFERENCE_FIELDS = {'path', 'blob_sha256', 'framework', 'selectors', 'ci_job'}
SOURCE_SCOPE_KINDS = {'type'}
TEST_FRAMEWORKS = {'dart_test', 'swift_xctest', 'workflow_executable'}
TEST_CI_JOBS = {'flutter', 'ios-native', 'native-sanitizers'}
REQUEST_DIRECTIONS = {'phone_to_glasses_request'}
EVENT_DIRECTIONS = {'glasses_to_phone_event'}
REQUEST_OPERATIONS = {'mutating_command', 'read_query'}
EVENT_OPERATIONS = {'stream_event', 'control_event'}
CHECK_KINDS = {'byte_equals', 'byte_in'}



@dataclass(frozen=True, slots=True)
class ValidationSubject:
    """Explicit immutable-by-reference subject for one validation invocation.

    The implementation module contains no repository-specific digest or source
    binding authority.  The single public facade constructs this value and
    passes it explicitly, so import order cannot change validation semantics.
    """

    expected_matrix_sha256: str
    expected_command_identities: Mapping[str, Mapping[str, str]]
    expected_profile_sha256: Mapping[str, str]


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

def string_sequence(value: Any, label: str, *, non_empty: bool=True) -> list[str]:
    """Validate an ordered string sequence while allowing repeated tokens."""
    if not isinstance(value, list) or (non_empty and not value):
        fail(f'{label} must be a string sequence')
    return [string(item, f'{label}[{index}]') for index, item in enumerate(value)]

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
    if not isinstance(command['tests'], list) or not command['tests']:
        fail(f'{label}.tests must be a non-empty test-binding list')
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

@dataclass(frozen=True, slots=True)
class LexToken:
    value: str
    start: int
    end: int


def _string_token(content: str) -> str:
    return 'STRING:' + content


def lex_source(text: str) -> list[LexToken]:
    """Tokenize Dart/Kotlin/Swift source while discarding comments.

    String literals are emitted as one token containing only their literal
    payload.  Consequently a whole code fragment hidden inside a comment or
    string cannot satisfy a multi-token source binding.
    """
    result: list[LexToken] = []
    index = 0
    length = len(text)
    multi = ('===', '!==', '>>>', '<<=', '>>=', '=>', '>=', '<=', '==', '!=',
             '&&', '||', '??', '?.', '..<', '...', '++', '--', '+=', '-=', '*=',
             '/=', '%=', '::', '->', '<<', '>>')
    while index < length:
        char = text[index]
        if char.isspace():
            index += 1
            continue
        if text.startswith('//', index):
            newline = text.find('\n', index + 2)
            index = length if newline < 0 else newline + 1
            continue
        if text.startswith('/*', index):
            depth = 1
            cursor = index + 2
            while cursor < length and depth:
                if text.startswith('/*', cursor):
                    depth += 1
                    cursor += 2
                elif text.startswith('*/', cursor):
                    depth -= 1
                    cursor += 2
                else:
                    cursor += 1
            if depth:
                fail('unterminated block comment in bound source')
            index = cursor
            continue

        raw_prefix = (
            char in {'r', 'R'}
            and index + 1 < length
            and text[index + 1] in {'\'', '"'}
            and (index == 0 or not (text[index - 1].isalnum() or text[index - 1] in {'_', '$'}))
        )
        quote_index = index + 1 if raw_prefix else index
        if text[quote_index] in {'\'', '"'}:
            quote = text[quote_index]
            triple = text.startswith(quote * 3, quote_index)
            delimiter = quote * (3 if triple else 1)
            cursor = quote_index + len(delimiter)
            content_start = cursor
            escaped = False
            while cursor < length:
                if not raw_prefix and not triple and escaped:
                    escaped = False
                    cursor += 1
                    continue
                if not raw_prefix and not triple and text[cursor] == '\\':
                    escaped = True
                    cursor += 1
                    continue
                if text.startswith(delimiter, cursor):
                    content = text[content_start:cursor]
                    end_index = cursor + len(delimiter)
                    result.append(LexToken(_string_token(content), index, end_index))
                    index = end_index
                    break
                cursor += 1
            else:
                fail('unterminated string literal in bound source')
            continue

        if char.isalpha() or char in {'_', '$'}:
            cursor = index + 1
            while cursor < length and (
                text[cursor].isalnum() or text[cursor] in {'_', '$'}
            ):
                cursor += 1
            result.append(LexToken(text[index:cursor], index, cursor))
            index = cursor
            continue
        if char.isdigit():
            cursor = index + 1
            while cursor < length and (
                text[cursor].isalnum() or text[cursor] in {'_', '.'}
            ):
                cursor += 1
            result.append(LexToken(text[index:cursor], index, cursor))
            index = cursor
            continue
        operator = next((value for value in multi if text.startswith(value, index)), None)
        if operator is not None:
            result.append(LexToken(operator, index, index + len(operator)))
            index += len(operator)
            continue
        result.append(LexToken(char, index, index + 1))
        index += 1
    return result


def token_values(text: str) -> list[str]:
    return [token.value for token in lex_source(text)]


def _matching_brace(tokens: list[LexToken], opening: int) -> int:
    depth = 0
    for index in range(opening, len(tokens)):
        if tokens[index].value == '{':
            depth += 1
        elif tokens[index].value == '}':
            depth -= 1
            if depth == 0:
                return index
    fail('unterminated source scope')


def _type_scope(tokens: list[LexToken], name: str) -> tuple[int, int]:
    declaration_kinds = {'class', 'object', 'struct', 'enum', 'extension', 'mixin', 'protocol'}
    candidates: list[tuple[int, int]] = []
    for index, token in enumerate(tokens):
        if token.value != name:
            continue
        if index == 0 or tokens[index - 1].value not in declaration_kinds:
            continue
        opening = next(
            (cursor for cursor in range(index + 1, min(len(tokens), index + 40))
             if tokens[cursor].value == '{'),
            None,
        )
        if opening is None:
            continue
        candidates.append((opening, _matching_brace(tokens, opening)))
    if len(candidates) != 1:
        fail(f'type scope {name!r} is not uniquely declared')
    return candidates[0]


def _subsequence_positions(values: list[str], expected: list[str]) -> list[int]:
    if not expected or len(expected) > len(values):
        return []
    width = len(expected)
    return [
        index
        for index in range(0, len(values) - width + 1)
        if values[index:index + width] == expected
    ]


def _static_false_ancestors(values: list[str]) -> list[set[int]]:
    ancestors: list[set[int]] = []
    stack: list[tuple[int, bool]] = []
    for index, value in enumerate(values):
        ancestors.append({opening for opening, dead in stack if dead})
        if value == '{':
            prefix = values[max(0, index - 5):index]
            dead = any(
                prefix[-len(pattern):] == pattern
                for pattern in (
                    ['if', '(', 'false', ')'],
                    ['if', '(', '0', ')'],
                    ['while', '(', 'false', ')'],
                    ['while', '(', '0', ')'],
                )
                if len(prefix) >= len(pattern)
            )
            stack.append((index, dead or any(parent_dead for _, parent_dead in stack)))
        elif value == '}':
            if not stack:
                fail('unbalanced closing brace in bound source')
            stack.pop()
    if stack:
        fail('unbalanced opening brace in bound source')
    return ancestors


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _hex_digest(value: Any, label: str) -> str:
    digest = string(value, label)
    if re.fullmatch(r'[0-9a-f]{64}', digest) is None:
        fail(f'{label} must be a lowercase SHA-256 digest')
    return digest


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
        path = repository_file(root, binding['path'], f'{identifier}.path')
        expected_blob = _hex_digest(binding['blob_sha256'], f'{identifier}.blob_sha256')
        if _sha256(path) != expected_blob:
            fail(f'{identifier} source blob digest mismatch')
        source = path.read_text(encoding='utf-8')
        tokens = lex_source(source)
        values = [token.value for token in tokens]
        scopes = binding['scopes']
        if not isinstance(scopes, list) or not scopes:
            fail(f'{identifier}.scopes must be a non-empty list')
        seen_scopes: set[tuple[str, str]] = set()
        seen_checks: set[str] = set()
        for scope_index, scope in enumerate(scopes):
            label = f'{identifier}.scopes[{scope_index}]'
            if not isinstance(scope, dict):
                fail(f'{label} must be an object')
            closed_shape(scope, SOURCE_SCOPE_FIELDS, label)
            kind = string(scope['kind'], f'{label}.kind')
            name = string(scope['name'], f'{label}.name')
            if kind not in SOURCE_SCOPE_KINDS:
                fail(f'{label}.kind is unsupported')
            scope_identity = (kind, name)
            if scope_identity in seen_scopes:
                fail(f'{identifier} contains duplicate source scope {scope_identity!r}')
            seen_scopes.add(scope_identity)
            opening, closing = _type_scope(tokens, name)
            scope_values = values[opening + 1:closing]
            dead_ancestors = _static_false_ancestors(scope_values)
            checks = scope['checks']
            if not isinstance(checks, list) or not checks:
                fail(f'{label}.checks must be a non-empty list')
            for check_index, check in enumerate(checks):
                check_label = f'{label}.checks[{check_index}]'
                if not isinstance(check, dict):
                    fail(f'{check_label} must be an object')
                closed_shape(check, SOURCE_CHECK_FIELDS, check_label)
                check_id = string(check['id'], f'{check_label}.id')
                if check_id in seen_checks:
                    fail(f'{identifier} contains duplicate check id {check_id!r}')
                seen_checks.add(check_id)
                expected_tokens = string_sequence(check['tokens'], f'{check_label}.tokens')
                occurrences = check['occurrences']
                if isinstance(occurrences, bool) or not isinstance(occurrences, int) or occurrences < 1:
                    fail(f'{check_label}.occurrences must be a positive integer')
                positions = _subsequence_positions(scope_values, expected_tokens)
                if len(positions) != occurrences:
                    fail(
                        f'{identifier}.{check_id} token sequence occurrence mismatch: '
                        f'{len(positions)} != {occurrences}'
                    )
                for position in positions:
                    if position < len(dead_ancestors) and dead_ancestors[position]:
                        fail(f'{identifier}.{check_id} exists only in a statically dead branch')
        result[identifier] = binding
    return result


def _discover_dart_tests(text: str) -> list[str]:
    values = [token.value for token in lex_source(text)]
    result: list[str] = []
    for index in range(len(values) - 2):
        if values[index] not in {'test', 'testWidgets'} or values[index + 1] != '(':
            continue
        token = values[index + 2]
        if not token.startswith('STRING:'):
            fail('Dart test declaration does not start with a literal selector')
        selector = token[len('STRING:'):]
        if selector in result:
            fail(f'duplicate Dart test selector: {selector}')
        result.append(selector)
    return result


def _discover_swift_tests(text: str) -> list[str]:
    values = [token.value for token in lex_source(text)]
    result: list[str] = []
    for index in range(len(values) - 2):
        if values[index] != 'func':
            continue
        selector = values[index + 1]
        if selector.startswith('test') and values[index + 2] == '(':
            if selector in result:
                fail(f'duplicate Swift test selector: {selector}')
            result.append(selector)
    return result


def validate_test_references(
    root: Path,
    value: Any,
    *,
    label: str,
) -> tuple[int, int]:
    if not isinstance(value, list) or not value:
        fail(f'{label}.tests must be a non-empty list')
    workflow = (root / '.github/workflows/ci.yml').read_text(encoding='utf-8')
    seen: set[tuple[str, str]] = set()
    selectors_total = 0
    for index, reference in enumerate(value):
        current = f'{label}.tests[{index}]'
        if not isinstance(reference, dict):
            fail(f'{current} must be an object')
        closed_shape(reference, TEST_REFERENCE_FIELDS, current)
        path_text = string(reference['path'], f'{current}.path')
        path = repository_file(root, path_text, f'{current}.path')
        if _sha256(path) != _hex_digest(reference['blob_sha256'], f'{current}.blob_sha256'):
            fail(f'{current} test blob digest mismatch')
        framework = string(reference['framework'], f'{current}.framework')
        ci_job = string(reference['ci_job'], f'{current}.ci_job')
        if framework not in TEST_FRAMEWORKS or ci_job not in TEST_CI_JOBS:
            fail(f'{current} framework or CI job is unsupported')
        selectors = string_list(reference['selectors'], f'{current}.selectors')
        text = path.read_text(encoding='utf-8')
        if framework == 'dart_test':
            if ci_job != 'flutter' or 'flutter test' not in workflow:
                fail(f'{current} is not bound to the Flutter test job')
            discovered = _discover_dart_tests(text)
        elif framework == 'swift_xctest':
            if ci_job != 'ios-native' or '-only-testing:RunnerTests' not in workflow:
                fail(f'{current} is not bound to the iOS native test job')
            discovered = _discover_swift_tests(text)
        else:
            if ci_job != 'native-sanitizers' or path_text not in workflow:
                fail(f'{current} executable is not bound to native-sanitizers')
            if stat.S_IMODE(path.stat().st_mode) & stat.S_IXUSR == 0:
                fail(f'{current} executable lacks owner execute permission')
            discovered = [path_text]
        for selector in selectors:
            identity = (path_text, selector)
            if identity in seen:
                fail(f'{label} contains duplicate test selector binding {identity!r}')
            seen.add(identity)
            if discovered.count(selector) != 1:
                fail(f'{current} selector is not uniquely discovered: {selector!r}')
        selectors_total += len(selectors)
    return len(value), selectors_total

def validate_document(
    root: Path,
    document: Mapping[str, Any],
    *,
    subject: ValidationSubject,
) -> dict[str, Any]:
    closed_shape(document, TOP_FIELDS, str(MATRIX))
    if document['schema_version'] != 3:
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
    if set(commands) != set(subject.expected_command_identities):
        fail(f'G1 command set drifted: {sorted(commands)!r}')
    base_commands = base.get('commands')
    if not isinstance(base_commands, dict):
        fail('base command map is malformed')
    used_bindings: set[str] = set()
    test_references = 0
    test_selectors = 0
    source_references = 0
    for identifier, expected_identity in subject.expected_command_identities.items():
        command = commands[identifier]
        validate_command(command, identifier)
        identity = {name: command[name] for name in ('command', 'direction', 'operation_kind', 'target', 'aggregation')}
        if identity != expected_identity:
            fail(f'{identifier} typed command identity drifted')
        if canonical_digest(command) != subject.expected_profile_sha256[identifier]:
            fail(f'{identifier} typed command profile drifted')
        base_key = BASE_COMMAND_KEYS.get(identifier)
        if base_key is not None and base_commands.get(base_key) != command['command']:
            fail(f'{identifier} command disagrees with base G1 contract')
        for binding_id in command['source_binding_ids']:
            if binding_id not in bindings:
                fail(f'{identifier} names an unknown source binding')
            used_bindings.add(binding_id)
        reference_count, selector_count = validate_test_references(
            root,
            command['tests'],
            label=identifier,
        )
        source_references += len(command['source_binding_ids'])
        test_references += reference_count
        test_selectors += selector_count
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
    if canonical_digest(document) != subject.expected_matrix_sha256:
        fail('typed G1 matrix canonical digest drifted')
    return {'ok': True, 'schema_version': 3, 'commands': len(commands), 'mutating_commands': sum((command['operation_kind'] == 'mutating_command' for command in commands.values())), 'typed_profiles': len(commands), 'source_bindings': len(bindings), 'source_references': source_references, 'test_references': test_references, 'test_selectors': test_selectors, 'producer_examples': sum((len(command['producer_examples']) for command in commands.values())), 'consumer_examples': sum((len(command['consumer_examples']) for command in commands.values())), 'vendor_confirmation_required': True, 'physical_qualification_required': True}
