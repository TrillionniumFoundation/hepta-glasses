"""Validated contracts for physical G1 qualification traces."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from math import ceil, isfinite
from typing import Any, Iterable, Mapping


class QualificationError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def _positive_integer(value: Any, *, code: str, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise QualificationError(code)
    return value


def _finite_number(value: Any, *, code: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise QualificationError(code)
    normalized = float(value)
    if not isfinite(normalized):
        raise QualificationError(code)
    return normalized


def percentile(values: list[int], percentile_value: float) -> int | None:
    if not values:
        return None
    if not 0 < percentile_value <= 100:
        raise ValueError("percentile must be in (0, 100]")
    ordered = sorted(values)
    index = max(0, ceil(percentile_value / 100 * len(ordered)) - 1)
    return ordered[index]


@dataclass(frozen=True)
class QualificationScenario:
    scenario_id: str
    platform: str
    minimum_duration_seconds: int
    maximum_wake_to_listening_p95_ms: int
    maximum_eos_to_first_display_p95_ms: int
    maximum_packet_loss_ratio: float
    maximum_temperature_c: float
    maximum_duplicate_effects: int
    minimum_end_battery_percent: float
    required_faults: frozenset[str]
    minimum_wake_to_listening_samples: int = 1
    minimum_eos_to_first_display_samples: int = 1
    minimum_packet_samples_per_side: int = 1
    minimum_battery_samples: int = 1
    minimum_temperature_samples: int = 1
    require_fault_recovery: bool = False

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "QualificationScenario":
        required = {
            "scenario_id",
            "platform",
            "minimum_duration_seconds",
            "maximum_wake_to_listening_p95_ms",
            "maximum_eos_to_first_display_p95_ms",
            "maximum_packet_loss_ratio",
            "maximum_temperature_c",
            "maximum_duplicate_effects",
            "minimum_end_battery_percent",
            "required_faults",
        }
        optional = {
            "minimum_wake_to_listening_samples",
            "minimum_eos_to_first_display_samples",
            "minimum_packet_samples_per_side",
            "minimum_battery_samples",
            "minimum_temperature_samples",
            "require_fault_recovery",
        }
        if required - set(value) or set(value) - required - optional:
            raise QualificationError("qualification_scenario_fields_invalid")
        scenario_id = value["scenario_id"]
        if not isinstance(scenario_id, str) or not scenario_id.strip():
            raise QualificationError("qualification_scenario_id_invalid")
        platform = value["platform"]
        if platform not in {"android", "ios"}:
            raise QualificationError("qualification_platform_invalid")
        required_faults = value["required_faults"]
        if (
            not isinstance(required_faults, list)
            or not required_faults
            or not all(isinstance(item, str) and item for item in required_faults)
            or len(set(required_faults)) != len(required_faults)
        ):
            raise QualificationError("qualification_faults_invalid")
        require_fault_recovery = value.get("require_fault_recovery", False)
        if not isinstance(require_fault_recovery, bool):
            raise QualificationError("qualification_fault_recovery_invalid")

        scenario = cls(
            scenario_id=scenario_id.strip(),
            platform=platform,
            minimum_duration_seconds=_positive_integer(
                value["minimum_duration_seconds"],
                code="qualification_duration_invalid",
            ),
            maximum_wake_to_listening_p95_ms=_positive_integer(
                value["maximum_wake_to_listening_p95_ms"],
                code="qualification_wake_threshold_invalid",
            ),
            maximum_eos_to_first_display_p95_ms=_positive_integer(
                value["maximum_eos_to_first_display_p95_ms"],
                code="qualification_display_threshold_invalid",
            ),
            maximum_packet_loss_ratio=_finite_number(
                value["maximum_packet_loss_ratio"],
                code="qualification_packet_loss_invalid",
            ),
            maximum_temperature_c=_finite_number(
                value["maximum_temperature_c"],
                code="qualification_temperature_invalid",
            ),
            maximum_duplicate_effects=_positive_integer(
                value["maximum_duplicate_effects"],
                code="qualification_duplicate_effects_invalid",
                minimum=0,
            ),
            minimum_end_battery_percent=_finite_number(
                value["minimum_end_battery_percent"],
                code="qualification_battery_invalid",
            ),
            required_faults=frozenset(required_faults),
            minimum_wake_to_listening_samples=_positive_integer(
                value.get("minimum_wake_to_listening_samples", 1),
                code="qualification_wake_sample_count_invalid",
            ),
            minimum_eos_to_first_display_samples=_positive_integer(
                value.get("minimum_eos_to_first_display_samples", 1),
                code="qualification_display_sample_count_invalid",
            ),
            minimum_packet_samples_per_side=_positive_integer(
                value.get("minimum_packet_samples_per_side", 1),
                code="qualification_packet_sample_count_invalid",
            ),
            minimum_battery_samples=_positive_integer(
                value.get("minimum_battery_samples", 1),
                code="qualification_battery_sample_count_invalid",
            ),
            minimum_temperature_samples=_positive_integer(
                value.get("minimum_temperature_samples", 1),
                code="qualification_temperature_sample_count_invalid",
            ),
            require_fault_recovery=require_fault_recovery,
        )
        if (
            not 0 <= scenario.maximum_packet_loss_ratio <= 1
            or not 0 <= scenario.minimum_end_battery_percent <= 100
        ):
            raise QualificationError("qualification_threshold_invalid")
        return scenario


@dataclass(frozen=True)
class TraceEvent:
    timestamp_ms: int
    event: str
    correlation_id: str | None = None
    side: str | None = None
    sequence: int | None = None
    effect_id: str | None = None
    battery_percent: float | None = None
    temperature_c: float | None = None
    fault: str | None = None
    capture_sequence: int | None = None
    generation: int | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "TraceEvent":
        allowed = {
            "timestamp_ms",
            "event",
            "correlation_id",
            "side",
            "sequence",
            "effect_id",
            "battery_percent",
            "temperature_c",
            "fault",
            "capture_sequence",
            "generation",
        }
        if set(value) - allowed:
            raise QualificationError("trace_event_fields_unknown")
        timestamp = value.get("timestamp_ms")
        event = value.get("event")
        if (
            isinstance(timestamp, bool)
            or not isinstance(timestamp, int)
            or timestamp < 0
            or not isinstance(event, str)
            or not event
        ):
            raise QualificationError("trace_event_invalid")
        side = value.get("side")
        if side is not None and side not in {"left", "right"}:
            raise QualificationError("trace_side_invalid")

        def optional_string(name: str) -> str | None:
            item = value.get(name)
            if item is not None and (not isinstance(item, str) or not item):
                raise QualificationError(f"trace_{name}_invalid")
            return item

        def optional_integer(name: str) -> int | None:
            item = value.get(name)
            if item is not None and (
                isinstance(item, bool) or not isinstance(item, int) or item < 0
            ):
                raise QualificationError(f"trace_{name}_invalid")
            return item

        battery = value.get("battery_percent")
        battery_value = None
        if battery is not None:
            battery_value = _finite_number(battery, code="trace_battery_invalid")
            if not 0 <= battery_value <= 100:
                raise QualificationError("trace_battery_invalid")
        temperature = value.get("temperature_c")
        temperature_value = None
        if temperature is not None:
            temperature_value = _finite_number(
                temperature,
                code="trace_temperature_invalid",
            )

        return cls(
            timestamp_ms=timestamp,
            event=event,
            correlation_id=optional_string("correlation_id"),
            side=side,
            sequence=optional_integer("sequence"),
            effect_id=optional_string("effect_id"),
            battery_percent=battery_value,
            temperature_c=temperature_value,
            fault=optional_string("fault"),
            capture_sequence=optional_integer("capture_sequence"),
            generation=optional_integer("generation"),
        )


