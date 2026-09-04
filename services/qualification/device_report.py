"""Deterministic evaluator for physical G1 qualification traces.

The evaluator preserves acquisition order. It never sorts a malformed trace into
an apparently valid one, and production scenarios require sufficient samples plus
observed and recovered fault evidence.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .device_report_contracts import (
    QualificationError,
    QualificationScenario,
    TraceEvent,
    _canonical,
    percentile,
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
        ordered = list(events)
        if len(ordered) < 2:
            raise QualificationError("trace_too_short")
        if any(
            later.timestamp_ms < earlier.timestamp_ms
            for earlier, later in zip(ordered, ordered[1:])
        ):
            raise QualificationError("trace_not_monotonic")
        self._validate_capture_sequence(ordered)

        duration_seconds = (
            ordered[-1].timestamp_ms - ordered[0].timestamp_ms
        ) / 1000
        wake_latencies = self._paired_latencies(
            ordered, start_event="wake", end_event="listening"
        )
        display_latencies = self._paired_latencies(
            ordered, start_event="end_of_speech", end_event="first_display"
        )
        packet_loss_ratio, packet_counts, duplicate_packets = self._packet_summary(
            ordered
        )
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
        injected_faults = self._faults(ordered, "fault_injected")
        observed_faults = self._faults(ordered, "fault_observed")
        recovered_faults = self._faults(ordered, "fault_recovered")

        wake_p95 = percentile(wake_latencies, 95)
        display_p95 = percentile(display_latencies, 95)
        max_temperature = max(temperatures) if temperatures else None
        end_battery = batteries[-1] if batteries else None
        enough_packets = all(
            packet_counts[side] >= scenario.minimum_packet_samples_per_side
            for side in ("left", "right")
        )
        fault_injection_complete = scenario.required_faults.issubset(injected_faults)
        fault_observation_complete = (
            not scenario.require_fault_recovery
            or scenario.required_faults.issubset(observed_faults)
        )
        fault_recovery_complete = (
            not scenario.require_fault_recovery
            or scenario.required_faults.issubset(recovered_faults)
        )
        checks = {
            "duration": duration_seconds >= scenario.minimum_duration_seconds,
            "wake_sample_count": len(wake_latencies)
            >= scenario.minimum_wake_to_listening_samples,
            "wake_to_listening_p95": wake_p95 is not None
            and wake_p95 <= scenario.maximum_wake_to_listening_p95_ms,
            "display_sample_count": len(display_latencies)
            >= scenario.minimum_eos_to_first_display_samples,
            "eos_to_first_display_p95": display_p95 is not None
            and display_p95 <= scenario.maximum_eos_to_first_display_p95_ms,
            "packet_sample_count": enough_packets,
            "packet_loss": packet_loss_ratio
            <= scenario.maximum_packet_loss_ratio,
            "temperature_sample_count": len(temperatures)
            >= scenario.minimum_temperature_samples,
            "temperature": max_temperature is not None
            and max_temperature <= scenario.maximum_temperature_c,
            "duplicate_effects": duplicate_effects
            <= scenario.maximum_duplicate_effects,
            "battery_sample_count": len(batteries)
            >= scenario.minimum_battery_samples,
            "end_battery": end_battery is not None
            and end_battery >= scenario.minimum_end_battery_percent,
            "required_faults_injected": fault_injection_complete,
            "required_faults_observed": fault_observation_complete,
            "required_faults_recovered": fault_recovery_complete,
        }
        serialized_trace = [event.__dict__ for event in ordered]
        metrics = {
            "duration_seconds": duration_seconds,
            "duplicate_effects": duplicate_effects,
            "duplicate_packets": duplicate_packets,
            "end_battery_percent": end_battery,
            "battery_sample_count": len(batteries),
            "eos_to_first_display_p95_ms": display_p95,
            "eos_to_first_display_sample_count": len(display_latencies),
            "maximum_temperature_c": max_temperature,
            "temperature_sample_count": len(temperatures),
            "injected_faults": sorted(injected_faults),
            "observed_faults": sorted(observed_faults),
            "recovered_faults": sorted(recovered_faults),
            "packet_counts": packet_counts,
            "packet_loss_ratio": packet_loss_ratio,
            "wake_to_listening_p95_ms": wake_p95,
            "wake_to_listening_sample_count": len(wake_latencies),
        }
        return QualificationReport(
            scenario_id=scenario.scenario_id,
            platform=scenario.platform,
            passed=all(checks.values()),
            checks=checks,
            metrics=metrics,
            # Digest the raw acquisition order, not a timestamp-sorted projection.
            trace_digest=hashlib.sha256(_canonical(serialized_trace)).hexdigest(),
            event_count=len(ordered),
        )

    @staticmethod
    def _validate_capture_sequence(events: list[TraceEvent]) -> None:
        supplied = [event.capture_sequence for event in events]
        if not any(value is not None for value in supplied):
            return
        if any(value is None for value in supplied):
            raise QualificationError("trace_capture_sequence_incomplete")
        values = [int(value) for value in supplied if value is not None]
        if any(later != earlier + 1 for earlier, later in zip(values, values[1:])):
            raise QualificationError("trace_capture_sequence_not_contiguous")

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
                if event.correlation_id in starts:
                    raise QualificationError("trace_correlation_reused")
                starts[event.correlation_id] = event.timestamp_ms
            elif event.event == end_event:
                start = starts.pop(event.correlation_id, None)
                if start is None:
                    raise QualificationError("trace_correlation_unmatched")
                latency = event.timestamp_ms - start
                if latency < 0:
                    raise QualificationError("trace_latency_negative")
                latencies.append(latency)
        return latencies

    @staticmethod
    def _packet_summary(
        events: list[TraceEvent],
    ) -> tuple[float, dict[str, int], int]:
        total_expected = 0
        total_seen = 0
        duplicate_packets = 0
        side_counts = {"left": 0, "right": 0}
        for side in ("left", "right"):
            grouped: dict[int, list[int]] = {}
            for event in events:
                if (
                    event.event == "packet_received"
                    and event.side == side
                    and event.sequence is not None
                ):
                    grouped.setdefault(event.generation or 0, []).append(event.sequence)
            for sequences in grouped.values():
                unique = sorted(set(sequences))
                duplicate_packets += len(sequences) - len(unique)
                side_counts[side] += len(unique)
                if not unique:
                    continue
                expected = unique[-1] - unique[0] + 1
                total_expected += expected
                total_seen += len(unique)
        if total_expected == 0:
            return 1.0, side_counts, duplicate_packets
        return (
            (total_expected - total_seen) / total_expected,
            side_counts,
            duplicate_packets,
        )

    @staticmethod
    def _faults(events: list[TraceEvent], event_name: str) -> set[str]:
        return {
            event.fault
            for event in events
            if event.event == event_name and event.fault is not None
        }
