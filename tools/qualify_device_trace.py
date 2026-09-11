#!/usr/bin/env python3
"""Evaluate a physical-device JSONL trace against a qualification scenario."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.qualification.device_report import (
    DeviceQualificationEvaluator,
    QualificationError,
    QualificationScenario,
    TraceEvent,
)


def load_trace(path: Path) -> list[TraceEvent]:
    events: list[TraceEvent] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            document = json.loads(line)
            if not isinstance(document, dict):
                raise QualificationError("trace_event_invalid")
            events.append(TraceEvent.from_mapping(document))
        except (json.JSONDecodeError, QualificationError) as error:
            raise QualificationError(f"trace_line_{line_number}_invalid") from error
    return events


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        scenario_document = json.loads(args.scenario.read_text(encoding="utf-8"))
        if not isinstance(scenario_document, dict):
            raise QualificationError("qualification_scenario_invalid")
        scenario = QualificationScenario.from_mapping(scenario_document)
        report = DeviceQualificationEvaluator().evaluate(
            scenario, load_trace(args.trace)
        )
    except (OSError, json.JSONDecodeError, QualificationError) as error:
        code = error.code if isinstance(error, QualificationError) else "qualification_input_invalid"
        print(json.dumps({"ok": False, "error": code}, separators=(",", ":")))
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report.to_mapping(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"ok": report.passed, "report": str(args.output)}))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
