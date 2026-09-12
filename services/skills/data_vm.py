"""Bounded data-only Skill execution with zero package-controlled egress.

The runtime interprets canonical JSON instructions from an already admitted
``CheckedSkill``. It never imports or executes package code, extracts files,
opens sockets, starts processes, or grants capability authority. Current
registry authority is resolved before execution and re-resolved before output
is released.
"""
from __future__ import annotations

import json
import math
import threading
import time
from dataclasses import dataclass
from typing import Callable

from services.skills.signed_package import canonical, fail, name, sha256
from services.skills.signed_registry import CheckedSkill, SignedSkillRegistry

MAX_PROGRAM_BYTES = 65536
MAX_INPUT_BYTES = 65536
MAX_OUTPUT_BYTES = 65536
MAX_WORKING_BYTES = 262144
MAX_STEPS = 256
MAX_COLLECTION = 256
MAX_DEPTH = 8
MAX_NODES = 2048
MAX_INTEGER = 9007199254740991
_ALLOWED_DATA_CLASSES = frozenset({"public", "personal", "sensitive"})


@dataclass(frozen=True)
class DataSkillInvocation:
    """Host-classified data passed to a pure R0 Skill program."""

    data: dict[str, object]
    data_classes: frozenset[str]


@dataclass(frozen=True)
class DataSkillResult:
    """Immutable canonical output bytes with a defensive decoded view."""

    output_json: bytes
    output_sha256: str
    manifest_sha256: str
    event_sequence: int
    instruction_count: int

    @property
    def output(self) -> object:
        return json.loads(self.output_json)


def _error(code: str) -> None:
    fail(code)


def _plain_json(value: object, *, byte_limit: int, code: str) -> object:
    """Capture and validate one defensive graph without reopening caller containers."""
    nodes = 0
    active: set[int] = set()

    def clone(item: object, depth: int) -> object:
        nonlocal nodes
        nodes += 1
        if nodes > MAX_NODES or depth > MAX_DEPTH:
            _error(code)

        if type(item) is dict:
            identity = id(item)
            if identity in active:
                _error(code)
            try:
                snapshot = item.copy()
            except (RuntimeError, TypeError, ValueError, RecursionError):
                _error(code)
            if len(snapshot) > MAX_COLLECTION:
                _error(code)
            active.add(identity)
            try:
                result: dict[str, object] = {}
                for key, child in snapshot.items():
                    if (type(key) is not str or not 1 <= len(key) <= 128
                            or any(ord(char) < 32 for char in key)):
                        _error(code)
                    result[key] = clone(child, depth + 1)
                return result
            finally:
                active.remove(identity)

        if type(item) is list:
            identity = id(item)
            if identity in active:
                _error(code)
            try:
                snapshot = item.copy()
            except (RuntimeError, TypeError, ValueError, RecursionError):
                _error(code)
            if len(snapshot) > MAX_COLLECTION:
                _error(code)
            active.add(identity)
            try:
                return [clone(child, depth + 1) for child in snapshot]
            finally:
                active.remove(identity)

        if type(item) is str:
            try:
                if len(item.encode("utf-8")) > byte_limit:
                    _error(code)
            except UnicodeError:
                _error(code)
            return item
        if type(item) is int:
            if abs(item) > MAX_INTEGER:
                _error(code)
            return item
        if type(item) is float:
            if not math.isfinite(item):
                _error(code)
            # Cross-language deterministic runtime deliberately excludes floats.
            _error(code)
        if item is None or type(item) is bool:
            return item
        _error(code)
        raise AssertionError("unreachable")

    try:
        captured = clone(value, 0)
        # Serialize only the captured built-in graph. Mutating the caller-owned
        # containers after capture cannot alter the bytes that were validated.
        encoded = canonical(captured)
    except (RuntimeError, TypeError, ValueError, UnicodeError, RecursionError):
        _error(code)
    if len(encoded) > byte_limit:
        _error(code)
    try:
        return json.loads(encoded)
    except (ValueError, UnicodeError, RecursionError):
        _error(code)
    raise AssertionError("unreachable")


def _parse_program(raw: bytes) -> dict[str, object]:
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_PROGRAM_BYTES:
        _error("skill_vm_program_size_invalid")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                _error("skill_vm_program_duplicate_key")
            result[key] = value
        return result

    try:
        program = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=lambda _: _error("skill_vm_program_format_invalid"),
        )
        if (type(program) is not dict
                or set(program) != {"schema_version", "steps", "result"}
                or type(program["schema_version"]) is not int
                or program["schema_version"] != 1
                or type(program["steps"]) is not list
                or not 1 <= len(program["steps"]) <= MAX_STEPS
                or type(program["result"]) is not str
                or canonical(program) != raw):
            _error("skill_vm_program_format_invalid")
    except (ValueError, TypeError, UnicodeError, RecursionError):
        _error("skill_vm_program_format_invalid")
    return program


def _identifier(value: object, code: str) -> str:
    if type(value) is not str:
        _error(code)
    try:
        return name(value)
    except Exception:
        _error(code)
    raise AssertionError("unreachable")


def _field(value: object) -> str:
    if (type(value) is not str or not 1 <= len(value) <= 128
            or any(ord(char) < 32 for char in value)):
        _error("skill_vm_object_field_invalid")
    return value


class DataSkillRuntime:
    """Execute a finite pure-data program admitted by ``SignedSkillRegistry``."""

    def __init__(self, registry: SignedSkillRegistry, *,
                 monotonic: Callable[[], float] = time.monotonic) -> None:
        if not isinstance(registry, SignedSkillRegistry) or not callable(monotonic):
            _error("skill_vm_configuration_invalid")
        self._registry = registry
        self._monotonic = monotonic

    def _time(self) -> float:
        try:
            value = self._monotonic()
        except Exception:
            _error("skill_vm_clock_invalid")
        if type(value) not in (int, float) or type(value) is bool or not math.isfinite(value):
            _error("skill_vm_clock_invalid")
        return float(value)

    def _checkpoint(self, *, stop: float, cancel: threading.Event | None) -> None:
        if cancel is not None and cancel.is_set():
            _error("skill_vm_cancelled")
        if self._time() >= stop:
            _error("skill_vm_deadline_expired")

    @staticmethod
    def _entrypoint(checked: CheckedSkill) -> tuple[dict, bytes]:
        if type(checked) is not CheckedSkill:
            _error("skill_vm_checked_skill_invalid")
        manifest = checked.manifest
        if (manifest.get("risk_tier") != "R0"
                or manifest.get("capabilities") != []
                or manifest.get("network_domains") != []):
            _error("skill_vm_policy_not_pure")
        path = manifest.get("entrypoint")
        if type(path) is not str or not path.endswith(".json"):
            _error("skill_vm_entrypoint_invalid")
        matches = [data for candidate, data in checked.files if candidate == path]
        if len(matches) != 1:
            _error("skill_vm_entrypoint_invalid")
        return manifest, matches[0]

    @staticmethod
    def _reference(values: dict[str, object], value: object) -> object:
        identifier = _identifier(value, "skill_vm_reference_invalid")
        if identifier not in values:
            _error("skill_vm_reference_invalid")
        return values[identifier]

    def execute(self, *, skill_id: str, package: bytes,
                invocation: DataSkillInvocation, timeout_seconds: float = 5,
                cancel: threading.Event | None = None) -> DataSkillResult:
        skill_id = _identifier(skill_id, "skill_vm_skill_id_invalid")
        if (type(package) is not bytes or type(invocation) is not DataSkillInvocation
                or type(invocation.data_classes) is not frozenset
                or not invocation.data_classes <= _ALLOWED_DATA_CLASSES
                or type(timeout_seconds) not in (int, float)
                or type(timeout_seconds) is bool
                or not math.isfinite(timeout_seconds)
                or not 0 < timeout_seconds <= 60
                or (cancel is not None and not isinstance(cancel, threading.Event))):
            _error("skill_vm_invocation_invalid")

        # A request already cancelled by its trusted host lifecycle must not
        # spend registry verification capacity merely to discover that fact.
        if cancel is not None and cancel.is_set():
            _error("skill_vm_cancelled")
        start = self._time()
        caller_stop = start + float(timeout_seconds)
        data = _plain_json(
            invocation.data, byte_limit=MAX_INPUT_BYTES,
            code="skill_vm_input_invalid",
        )
        # Input capture is bounded but can consume caller time. Recheck before
        # the first expensive signature/package/dependency registry resolution.
        self._checkpoint(stop=caller_stop, cancel=cancel)
        checked = self._registry.resolve(skill_id, package=package)
        manifest, raw_program = self._entrypoint(checked)
        if not invocation.data_classes <= frozenset(manifest.get("data_classes", [])):
            _error("skill_vm_data_class_not_declared")
        manifest_timeout = manifest.get("timeout_ms")
        if type(manifest_timeout) is not int or not 1 <= manifest_timeout <= 300000:
            _error("skill_vm_manifest_timeout_invalid")
        stop = min(caller_stop, start + manifest_timeout / 1000.0)
        self._checkpoint(stop=stop, cancel=cancel)
        program = _parse_program(raw_program)

        values: dict[str, object] = {}
        working_bytes = 0
        for step in program["steps"]:
            self._checkpoint(stop=stop, cancel=cancel)
            if type(step) is not dict or type(step.get("op")) is not str:
                _error("skill_vm_instruction_invalid")
            identifier = _identifier(step.get("id"), "skill_vm_instruction_id_invalid")
            if identifier in values:
                _error("skill_vm_instruction_id_invalid")
            op = step["op"]

            if op == "literal":
                if set(step) != {"id", "op", "value"}:
                    _error("skill_vm_instruction_invalid")
                result = _plain_json(step["value"], byte_limit=MAX_OUTPUT_BYTES,
                                     code="skill_vm_value_invalid")
            elif op == "input":
                if set(step) != {"id", "op", "path"} or type(step["path"]) is not list or len(step["path"]) > 16:
                    _error("skill_vm_instruction_invalid")
                result = data
                for part in step["path"]:
                    if type(result) is dict and type(part) is str and part in result:
                        result = result[part]
                    elif (type(result) is list and type(part) is int and type(part) is not bool
                          and 0 <= part < len(result)):
                        result = result[part]
                    else:
                        _error("skill_vm_input_path_missing")
            elif op in {"lower", "upper", "length"}:
                if set(step) != {"id", "op", "value"}:
                    _error("skill_vm_instruction_invalid")
                source = self._reference(values, step["value"])
                if op == "lower" or op == "upper":
                    if type(source) is not str:
                        _error("skill_vm_type_mismatch")
                    result = source.lower() if op == "lower" else source.upper()
                else:
                    if type(source) not in (str, list, dict):
                        _error("skill_vm_type_mismatch")
                    result = len(source)
            elif op == "concat":
                if set(step) != {"id", "op", "items"} or type(step["items"]) is not list or not 1 <= len(step["items"]) <= 32:
                    _error("skill_vm_instruction_invalid")
                parts = [self._reference(values, item) for item in step["items"]]
                if any(type(part) is not str for part in parts):
                    _error("skill_vm_type_mismatch")
                result = "".join(parts)
            elif op == "array":
                if set(step) != {"id", "op", "items"} or type(step["items"]) is not list or len(step["items"]) > 64:
                    _error("skill_vm_instruction_invalid")
                result = [self._reference(values, item) for item in step["items"]]
            elif op == "object":
                if set(step) != {"id", "op", "fields"} or type(step["fields"]) is not dict or len(step["fields"]) > 64:
                    _error("skill_vm_instruction_invalid")
                result = {_field(key): self._reference(values, reference)
                          for key, reference in step["fields"].items()}
            elif op == "equal":
                if set(step) != {"id", "op", "left", "right"}:
                    _error("skill_vm_instruction_invalid")
                result = self._reference(values, step["left"]) == self._reference(values, step["right"])
            elif op == "select":
                if set(step) != {"id", "op", "condition", "when_true", "when_false"}:
                    _error("skill_vm_instruction_invalid")
                condition = self._reference(values, step["condition"])
                if type(condition) is not bool:
                    _error("skill_vm_type_mismatch")
                result = self._reference(values, step["when_true"] if condition else step["when_false"])
            elif op == "slice":
                if set(step) != {"id", "op", "value", "start", "end"}:
                    _error("skill_vm_instruction_invalid")
                source = self._reference(values, step["value"])
                start_index, end_index = step["start"], step["end"]
                if (type(source) not in (str, list) or type(start_index) is not int
                        or type(start_index) is bool or type(end_index) is not int
                        or type(end_index) is bool or not 0 <= start_index <= end_index <= MAX_COLLECTION):
                    _error("skill_vm_type_mismatch")
                result = source[start_index:end_index]
            else:
                _error("skill_vm_opcode_forbidden")

            result = _plain_json(result, byte_limit=MAX_OUTPUT_BYTES,
                                 code="skill_vm_value_invalid")
            size = len(canonical(result))
            working_bytes += size
            if working_bytes > MAX_WORKING_BYTES:
                _error("skill_vm_working_set_exhausted")
            values[identifier] = result
            self._checkpoint(stop=stop, cancel=cancel)

        result_id = _identifier(program["result"], "skill_vm_result_invalid")
        if result_id not in values:
            _error("skill_vm_result_invalid")
        output_json = canonical(values[result_id])
        if len(output_json) > MAX_OUTPUT_BYTES:
            _error("skill_vm_output_too_large")

        # Re-run the registry's signature, package, dependency, consent and
        # revocation checks after computation. A stale snapshot never releases
        # output. The package program itself cannot affect this call.
        final = self._registry.resolve(skill_id, package=package)
        if (final.document != checked.document
                or final.files != checked.files
                or final.event_sequence != checked.event_sequence
                or final.consent_expires_at != checked.consent_expires_at):
            _error("skill_vm_admission_changed")
        self._checkpoint(stop=stop, cancel=cancel)
        return DataSkillResult(
            output_json=output_json,
            output_sha256=sha256(output_json),
            manifest_sha256=sha256(checked.document),
            event_sequence=checked.event_sequence,
            instruction_count=len(program["steps"]),
        )
