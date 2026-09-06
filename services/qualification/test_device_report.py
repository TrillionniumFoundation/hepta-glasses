from __future__ import annotations

import unittest

from services.qualification.device_report import (
    DeviceQualificationEvaluator,
    QualificationError,
    QualificationScenario,
    TraceEvent,
)


class DeviceQualificationTest(unittest.TestCase):
    def scenario(
        self,
        platform: str = "android",
        *,
        require_fault_recovery: bool = False,
    ) -> QualificationScenario:
        document: dict[str, object] = {
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
        if require_fault_recovery:
            document.update(
                {
                    "minimum_wake_to_listening_samples": 2,
                    "minimum_eos_to_first_display_samples": 2,
                    "minimum_packet_samples_per_side": 20,
                    "minimum_battery_samples": 2,
                    "minimum_temperature_samples": 2,
                    "require_fault_recovery": True,
                }
            )
        return QualificationScenario.from_mapping(document)

    def passing_events(
        self,
        *,
        fault_recovery: bool = False,
        capture_sequence: bool = False,
    ) -> list[TraceEvent]:
        events = [
            TraceEvent(0, "battery", battery_percent=90, temperature_c=30),
            TraceEvent(100, "wake", correlation_id="a"),
            TraceEvent(350, "listening", correlation_id="a"),
            TraceEvent(1_000, "end_of_speech", correlation_id="a"),
            TraceEvent(2_100, "first_display", correlation_id="a"),
            TraceEvent(2_200, "wake", correlation_id="b"),
            TraceEvent(2_450, "listening", correlation_id="b"),
            TraceEvent(2_600, "end_of_speech", correlation_id="b"),
            TraceEvent(3_700, "first_display", correlation_id="b"),
            TraceEvent(4_000, "fault_injected", fault="left_disconnect"),
            TraceEvent(5_000, "fault_injected", fault="network_handoff"),
            TraceEvent(6_000, "effect_committed", effect_id="effect-1"),
        ]
        if fault_recovery:
            events.extend(
                [
                    TraceEvent(7_000, "fault_observed", fault="left_disconnect"),
                    TraceEvent(8_000, "fault_recovered", fault="left_disconnect"),
                    TraceEvent(9_000, "fault_observed", fault="network_handoff"),
                    TraceEvent(10_000, "fault_recovered", fault="network_handoff"),
                ]
            )
        for sequence in range(1, 21):
            events.append(
                TraceEvent(
                    11_000 + sequence * 2,
                    "packet_received",
                    side="left",
                    sequence=sequence,
                    generation=1,
                )
            )
            events.append(
                TraceEvent(
                    11_001 + sequence * 2,
                    "packet_received",
                    side="right",
                    sequence=sequence,
                    generation=1,
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
        if capture_sequence:
            events = [
                TraceEvent(
                    **{
                        **event.__dict__,
                        "capture_sequence": index + 100,
                    }
                )
                for index, event in enumerate(events)
            ]
        return events

    def test_passing_trace_produces_digest_and_all_checks(self) -> None:
        report = DeviceQualificationEvaluator().evaluate(
            self.scenario(), self.passing_events()
        )
        self.assertTrue(report.passed, report.checks)
        self.assertEqual(len(report.trace_digest), 64)
        self.assertTrue(all(report.checks.values()))

    def test_duplicate_effect_and_missing_fault_fail_gate(self) -> None:
        events = self.passing_events()
        events.append(
            TraceEvent(66_000, "effect_committed", effect_id="effect-1")
        )
        events = [event for event in events if event.fault != "network_handoff"]
        report = DeviceQualificationEvaluator().evaluate(self.scenario(), events)
        self.assertFalse(report.passed)
        self.assertFalse(report.checks["duplicate_effects"])
        self.assertFalse(report.checks["required_faults_injected"])

    def test_raw_out_of_order_trace_is_rejected_instead_of_sorted(self) -> None:
        events = self.passing_events()
        events[3], events[4] = events[4], events[3]
        with self.assertRaisesRegex(QualificationError, "trace_not_monotonic"):
            DeviceQualificationEvaluator().evaluate(self.scenario(), events)

    def test_capture_sequence_must_be_complete_and_contiguous(self) -> None:
        events = self.passing_events(capture_sequence=True)
        events[5] = TraceEvent(
            **{
                **events[5].__dict__,
                "capture_sequence": events[5].capture_sequence + 2,
            }
        )
        with self.assertRaisesRegex(
            QualificationError,
            "trace_capture_sequence_not_contiguous",
        ):
            DeviceQualificationEvaluator().evaluate(self.scenario(), events)

    def test_production_faults_require_observation_and_recovery(self) -> None:
        scenario = self.scenario(require_fault_recovery=True)
        missing_recovery = DeviceQualificationEvaluator().evaluate(
            scenario,
            self.passing_events(),
        )
        self.assertFalse(missing_recovery.passed)
        self.assertFalse(missing_recovery.checks["required_faults_observed"])
        self.assertFalse(missing_recovery.checks["required_faults_recovered"])

        complete = DeviceQualificationEvaluator().evaluate(
            scenario,
            self.passing_events(fault_recovery=True, capture_sequence=True),
        )
        self.assertTrue(complete.passed, complete.checks)

    def test_minimum_sample_counts_are_enforced(self) -> None:
        scenario = QualificationScenario.from_mapping(
            {
                "scenario_id": "samples",
                "platform": "ios",
                "minimum_duration_seconds": 1,
                "maximum_wake_to_listening_p95_ms": 1000,
                "maximum_eos_to_first_display_p95_ms": 1000,
                "maximum_packet_loss_ratio": 1.0,
                "maximum_temperature_c": 100.0,
                "maximum_duplicate_effects": 0,
                "minimum_end_battery_percent": 0,
                "required_faults": ["left_disconnect"],
                "minimum_wake_to_listening_samples": 3,
                "minimum_eos_to_first_display_samples": 3,
                "minimum_packet_samples_per_side": 30,
                "minimum_battery_samples": 3,
                "minimum_temperature_samples": 3,
            }
        )
        report = DeviceQualificationEvaluator().evaluate(
            scenario,
            self.passing_events(),
        )
        self.assertFalse(report.passed)
        self.assertFalse(report.checks["wake_sample_count"])
        self.assertFalse(report.checks["display_sample_count"])
        self.assertFalse(report.checks["packet_sample_count"])
        self.assertFalse(report.checks["battery_sample_count"])
        self.assertFalse(report.checks["temperature_sample_count"])


if __name__ == "__main__":
    unittest.main()
