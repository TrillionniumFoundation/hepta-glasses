from __future__ import annotations

import unittest

from services.qualification.device_report import (
    DeviceQualificationEvaluator,
    QualificationScenario,
    TraceEvent,
)


class DeviceQualificationTest(unittest.TestCase):
    def scenario(self, platform: str = "android") -> QualificationScenario:
        return QualificationScenario.from_mapping(
            {
                "scenario_id": "g1-soak-v1",
                "platform": platform,
                "minimum_duration_seconds": 60,
                "maximum_wake_to_listening_p95_ms": 300,
                "maximum_eos_to_first_display_p95_ms": 1500,
                "maximum_packet_loss_ratio": 0.05,
                "maximum_temperature_c": 42.0,
                "maximum_duplicate_effects": 0,
                "minimum_end_battery_percent": 20.0,
                "required_faults": ["left_disconnect", "network_handoff"],
            }
        )

    def passing_events(self) -> list[TraceEvent]:
        events = [
            TraceEvent(0, "battery", battery_percent=90, temperature_c=30),
            TraceEvent(100, "wake", correlation_id="a"),
            TraceEvent(350, "listening", correlation_id="a"),
            TraceEvent(1_000, "end_of_speech", correlation_id="a"),
            TraceEvent(2_100, "first_display", correlation_id="a"),
            TraceEvent(3_000, "fault_injected", fault="left_disconnect"),
            TraceEvent(4_000, "fault_injected", fault="network_handoff"),
            TraceEvent(5_000, "effect_committed", effect_id="effect-1"),
        ]
        for sequence in range(1, 21):
            events.append(
                TraceEvent(
                    6_000 + sequence,
                    "packet_received",
                    side="left",
                    sequence=sequence,
                )
            )
            events.append(
                TraceEvent(
                    7_000 + sequence,
                    "packet_received",
                    side="right",
                    sequence=sequence,
                )
            )
        events.append(
            TraceEvent(
                65_000,
                "battery",
                battery_percent=70,
                temperature_c=38,
            )
        )
        return events

    def test_passing_trace_produces_digest_and_all_checks(self) -> None:
        report = DeviceQualificationEvaluator().evaluate(
            self.scenario(), self.passing_events()
        )
        self.assertTrue(report.passed)
        self.assertEqual(len(report.trace_digest), 64)
        self.assertTrue(all(report.checks.values()))

    def test_duplicate_effect_and_missing_fault_fail_gate(self) -> None:
        events = self.passing_events()
        events.append(
            TraceEvent(60_000, "effect_committed", effect_id="effect-1")
        )
        events = [event for event in events if event.fault != "network_handoff"]
        report = DeviceQualificationEvaluator().evaluate(self.scenario(), events)
        self.assertFalse(report.passed)
        self.assertFalse(report.checks["duplicate_effects"])
        self.assertFalse(report.checks["required_faults"])


if __name__ == "__main__":
    unittest.main()
