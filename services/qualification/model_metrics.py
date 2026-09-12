"""One-shot local model-capacity metrics; not a readiness or release gate.

The trusted operator supplies an existing absolute database path. No listener,
provider call, identifiers, credentials, writes or automatic recovery are added.
Exit 0: observed with no attention flag; 2: observed, attention required;
1: unavailable, emit only the failed-observation gauge, never zero capacity.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from services.qualification.model_capacity import CapacityObservationError, read_snapshot


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        # Do not reflect private arguments; reserve status 2 for real attention.
        raise CapacityObservationError("model_metrics_arguments_invalid")


def _gauge(name: str, value: int) -> str:
    # Only fixed source names and locally derived integers reach this function.
    return f'# TYPE hepta_model_{name} gauge\nhepta_model_{name} {value}\n'


def collect(path: Path, *, timeout_seconds: float = 2.0) -> tuple[str, int]:
    """Read exactly one observer snapshot and render fixed, label-free gauges.

    Errors propagate to the CLI; partial or cached success output is never used.
    These are local diagnostics, not provider state, service health or authority.
    """
    snapshot = read_snapshot(path, timeout_seconds=timeout_seconds)
    values = [('observation_success', 1),
              ('suspended', int(snapshot['suspended'])),
              ('operator_attention_required', int(snapshot['operator_attention_required'])),
              ('event_rows', snapshot['event_rows']),
              ('unresolved_readback_exhausted', snapshot['unresolved_readback_exhausted'])]
    for group in ('requests', 'denials'):
        for field in ('used', 'limit', 'remaining', 'utilization_basis_points'):
            values.append((f'{group}_{field}', snapshot[group][field]))
    for state in ('prepared', 'indeterminate', 'committed', 'cancelled'):
        values.append((f'requests_{state}', snapshot['states'][state]))
    return ''.join(_gauge(name, value) for name, value in values), (
        2 if snapshot['operator_attention_required'] else 0
    )


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--timeout-seconds', type=float, default=2.0)
    try:
        args = parser.parse_args(argv)
        output, status = collect(args.database, timeout_seconds=args.timeout_seconds)
    except CapacityObservationError as error:
        print(_gauge('observation_success', 0), end='')
        print(json.dumps({'ok': False, 'code': str(error), 'release_authority': False}),
              file=sys.stderr)
        return 1
    print(output, end='')
    return status


if __name__ == '__main__':
    raise SystemExit(main())
