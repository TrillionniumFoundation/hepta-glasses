# Physical G1 qualification runbook

## Inputs

- exact application commit and tree;
- signed Android or iOS test build identity;
- G1 firmware and serial identifiers;
- platform and device model;
- scenario file under `evidence/templates/`;
- JSONL trace with monotonic millisecond timestamps;
- operator and lab identifiers stored outside sensitive user data.

## Required trace events

`wake`, `listening`, `end_of_speech`, `first_display`, `packet_received`, `effect_committed`, `fault_injected`, and battery/temperature samples. Correlation IDs pair latency events. Effect IDs detect duplicate side effects. Packet sequences are evaluated independently for left and right legs.

## Execute

```bash
python3 tools/qualify_device_trace.py \
  --scenario evidence/templates/android-g1-qualification-scenario.json \
  --trace evidence/device/android/<session>.jsonl \
  --output evidence/device/android/<session>.report.json
```

Repeat with the iOS scenario. Synthetic traces are permitted only for evaluator tests and cannot be placed in the physical evidence index.

## Required faults

Left, right and dual disconnect; network handoff; token expiry; model timeout; application restart; user cancel before effect; and an external effect that completes after the local timeout.
