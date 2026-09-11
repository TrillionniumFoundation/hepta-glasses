# Physical G1 qualification runbook

## 1. Authority and inputs

A physical report requires all of the following before collection:

- exact application commit and tree;
- signed Android or iOS test-build digest;
- G1 firmware version and left/right serial or attested pair identity;
- platform, OS version, device model, locale, and radio environment;
- the exact scenario file under `evidence/templates/`;
- a capture tool version and operator/lab identity controlled outside user data;
- a raw JSONL trace preserved in acquisition order; and
- a monotonic capture sequence when the collector can supply one.

Synthetic traces are permitted only for evaluator tests. They cannot enter the
physical evidence index or close HG-0010/HG-0018.

## 2. Trace integrity

The evaluator no longer timestamp-sorts input. A timestamp regression fails as
`trace_not_monotonic`; it is never silently rearranged into a passing trace. If
one event supplies `capture_sequence`, every event must supply it and values must
be contiguous. The report digest covers the raw acquisition order.

Recommended event shape:

```json
{
  "capture_sequence": 1042,
  "timestamp_ms": 923441,
  "event": "packet_received",
  "side": "left",
  "generation": 7,
  "sequence": 83,
  "correlation_id": "opaque-id"
}
```

Do not splice sessions, devices, firmware versions, or generations into one trace.
Preserve the raw file, collector logs, and signature separately from the derived
report.

## 3. Required events and sample floors

Production scenarios require:

- at least 30 `wake` → `listening` pairs;
- at least 30 `end_of_speech` → `first_display` pairs;
- at least 1,000 unique packet sequences for each side, grouped by connection
  generation before loss is calculated;
- at least 12 battery samples and 12 temperature samples over at least one hour;
- zero duplicate committed effect IDs; and
- every required fault to have `fault_injected`, `fault_observed`, and
  `fault_recovered` events.

The required fault set is left disconnect, right disconnect, dual disconnect,
network handoff, token expiry, model timeout, application restart, user
cancellation before effect, and an external effect completing after local timeout.
A label saying a fault was injected is not proof that the system observed or
recovered from it.

## 4. Execute

```bash
python3 tools/qualify_device_trace.py \
  --scenario evidence/templates/android-g1-qualification-scenario.json \
  --trace evidence/device/android/<session>.jsonl \
  --output evidence/device/android/<session>.report.json
```

Repeat with the iOS scenario. A passing derived report remains untrusted until the
raw trace, report, build, device, firmware, scenario, and lab statement are signed
by the enrolled physical-lab authority and accepted through the G10 evidence
package.

## 5. Negative and custody checks

Before accepting a collector release, prove that the evaluator rejects:

- timestamp regression and non-contiguous capture sequence;
- truncated final records, malformed JSON, unknown fields, non-finite telemetry,
  invalid side/generation/sequence values, and duplicate correlation starts;
- missing sample floors, missing fault observation/recovery, duplicate effects,
  excessive loss/latency/temperature, and insufficient battery;
- traces whose report digest changes after any event reordering; and
- a valid report rebound to another app build, firmware, device, scenario, or
  authority package.

Physical evidence expires or reopens when any bound identity changes or the lab
withdraws its statement.
