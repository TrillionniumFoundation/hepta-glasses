"""Deterministic evaluator for physical G1 qualification traces."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from math import ceil
from typing import Any, Iterable, Mapping


class QualificationError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


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
        if set(value) != required:
            raise QualificationError("qualification_scenario_fields_invalid")
        platform = value["platform"]
        if platform not in {"android", "ios"}:
            raise QualificationError("qualification_platform_invalid")
        required_faults = value["required_faults"]
        if not isinstance(required_faults, list) or not all(
            isinstance(item, str) and item for item in required_faults
        ):
            raise QualificationError("qualification_faults_invalid")
        scenario = cls(
            scenario_id=str(value["scenario_id"]),
            platform=platform,
            minimum_duration_seconds=int(value["minimum_duration_seconds"]),
            maximum_wake_to_listening_p95_ms=int(
                value["maximum_wake_to_listening_p95_ms"]
            ),
            maximum_eos_to_first_display_p95_ms=int(
                value["maximum_eos_to_first_display_p95_ms"]
            ),
            maximum_packet_loss_ratio=float(value["maximum_packet_loss_ratio"]),
            maximum_temperature_c=float(value["maximum_temperature_c"]),
            maximum_duplicate_effects=int(value["maximum_duplicate_effects"]),
            minimum_end_battery_percent=float(value["minimum_end_battery_percent"]),
            required_faults=frozenset(required_faults),
        )
        if (
            scenario.minimum_duration_seconds < 1
            or scenario.maximum_wake_to_listening_p95_ms < 1
            or scenario.maximum_eos_to_first_display_p95_ms < 1
            or not 0 <= scenario.maximum_packet_loss_ratio <= 1
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
        }
        if set(value) - allowed:
            raise QualificationError("trace_event_fields_unknown")
        if not isinstance(value.get("timestamp_ms"), int) or not isinstance(
            value.get("event"), str
        ):
            raise QualificationError("trace_event_invalid")
        side = value.get("side")
        if side is not None and side not in {"left", "right"}:
            raise QualificationError("trace_side_invalid")
        return cls(
            timestamp_ms=value["timestamp_ms"],
            event=value["event"],
            correlation_id=value.get("correlation_id"),
            side=side,
            sequence=value.get("sequence"),
            effect_id=value.get("effect_id"),
            battery_percent=(
                float(value["battery_percent"])
                if value.get("battery_percent") is not None
                else None
            ),
            temperature_c=(
                float(value["temperature_c"])
                if value.get("temperature_c") is not None
                else None
            ),
            fault=value.get("fault"),
        )


@dataclass(frozen=True)
class QualificationReport:
    scenario_id: str
    platform: str
    passed: bool
    checks: Mapping[str, bool]
    metrics: Mapping[str, Any]
    trace_digest: str
    event_count: int

    def to_mapping(self) -> dict[str, Any]:
        return {
            "checks": dict(self.checks),
            "event_count": self.event_count,
            "metrics": dict(self.metrics),
            "passed": self.passed,
            "platform": self.platform,
            "scenario_id": self.scenario_id,
            "trace_digest": self.trace_digest,
        }


class DeviceQualificationEvaluator:
    def evaluate(
        self,
        scenario: QualificationScenario,
        events: Iterable[TraceEvent],
    ) -> QualificationReport:
        ordered = sorted(events, key=lambda item: item.timestamp_ms)
        if len(ordered) < 2:
            raise QualificationError("trace_too_short")
        if any(
            later.timestamp_ms < earlier.timestamp_ms
            for earlier, later in zip(ordered, ordered[1:])
        ):
            raise QualificationError("trace_not_monotonic")

        duration_seconds = (
            ordered[-1].timestamp_ms - ordered[0].timestamp_ms
        ) / 1000
        wake_latencies = self._paired_latencies(
            ordered, start_event="wake", end_event="listening"
        )
        display_latencies = self._paired_latencies(
            ordered, start_event="end_of_speech", end_event="first_display"
        )
        packet_loss_ratio = self._packet_loss_ratio(ordered)
        effects = [
            event.effect_id
            for event in ordered
            if event.event == "effect_committed" and event.effect_id
        ]
        duplicate_effects = len(effects) - len(set(effects))
        temperatures = [
            event.temperature_c
            for event in ordered
            if event.temperature_c is not None
        ]
        batteries = [
            event.battery_percent
            for event in ordered
            if event.battery_percent is not None
        ]
        observed_faults = {
            event.fault
            for event in ordered
            if event.event == "fault_injected" and event.fault
        }

        wake_p95 = percentile(wake_latencies, 95)
        display_p95 = percentile(display_latencies, 95)
        max_temperature = max(temperatures) if temperatures else None
        end_battery = batteries[-1] if batteries else None
        checks = {
            "duration": duration_seconds >= scenario.minimum_duration_seconds,
            "wake_to_listening_p95": wake_p95 is not None
            and wake_p95 <= scenario.maximum_wake_to_listening_p95_ms,
            "eos_to_first_display_p95": display_p95 is not None
            and display_p95 <= scenario.maximum_eos_to_first_display_p95_ms,
            "packet_loss": packet_loss_ratio
            <= scenario.maximum_packet_loss_ratio,
            "temperature": max_temperature is not None
            and max_temperature <= scenario.maximum_temperature_c,
            "duplicate_effects": duplicate_effects
            <= scenario.maximum_duplicate_effects,
            "end_battery": end_battery is not None
            and end_battery >= scenario.minimum_end_battery_percent,
            "required_faults": scenario.required_faults.issubset(observed_faults),
        }
        serialized_trace = [event.__dict__ for event in ordered]
        metrics = {
            "duration_seconds": duration_seconds,
            "duplicate_effects": duplicate_effects,
            "end_battery_percent": end_battery,
            "eos_to_first_display_p95_ms": display_p95,
            "maximum_temperature_c": max_temperature,
            "observed_faults": sorted(observed_faults),
            "packet_loss_ratio": packet_loss_ratio,
            "wake_to_listening_p95_ms": wake_p95,
        }
        return QualificationReport(
            scenario_id=scenario.scenario_id,
            platform=scenario.platform,
            passed=all(checks.values()),
            checks=checks,
            metrics=metrics,
            trace_digest=hashlib.sha256(_canonical(serialized_trace)).hexdigest(),
            event_count=len(ordered),
        )

    @staticmethod
    def _paired_latencies(
        events: list[TraceEvent], *, start_event: str, end_event: str
    ) -> list[int]:
        starts: dict[str, int] = {}
        latencies: list[int] = []
        for event in events:
            if event.correlation_id is None:
                continue
            if event.event == start_event:
                starts[event.correlation_id] = event.timestamp_ms
            elif event.event == end_event and event.correlation_id in starts:
                latency = event.timestamp_ms - starts.pop(event.correlation_id)
                if latency >= 0:
                    latencies.append(latency)
        return latencies

    @staticmethod
    def _packet_loss_ratio(events: list[TraceEvent]) -> float:
        total_expected = 0
        total_seen = 0
        for side in ("left", "right"):
            sequences = sorted(
                {
                    event.sequence
                    for event in events
                    if event.event == "packet_received"
                    and event.side == side
                    and event.sequence is not None
                }
            )
            if not sequences:
                continue
            expected = sequences[-1] - sequences[0] + 1
            total_expected += expected
            total_seen += len(sequences)
        if total_expected == 0:
            return 1.0
        return (total_expected - total_seen) / total_expected
