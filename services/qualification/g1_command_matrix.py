"""Single authoritative entry point for the typed G1 command matrix.

Repository-specific digests and command identities live only here.  The
implementation module is a pure library and receives an explicit validation
subject; imports never mutate shared module state and no second validator CLI
exists.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any, Mapping

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from services.qualification import g1_command_matrix_impl as _impl

EXPECTED_MATRIX_SHA256 = '6779c7cc417c193cf631c8e7ff3dea56571693e5bbf4a7597305f27d27987369'
EXPECTED_COMMAND_IDENTITIES = {'bitmap_crc': {'aggregation': 'staged_single_leg_transfer',
                'command': '0x16',
                'direction': 'phone_to_glasses_request',
                'operation_kind': 'mutating_command',
                'target': 'active_bitmap_leg'},
 'bitmap_finish': {'aggregation': 'staged_single_leg_transfer',
                   'command': '0x20',
                   'direction': 'phone_to_glasses_request',
                   'operation_kind': 'mutating_command',
                   'target': 'active_bitmap_leg'},
 'bitmap_packet': {'aggregation': 'staged_single_leg_transfer',
                   'command': '0x15',
                   'direction': 'phone_to_glasses_request',
                   'operation_kind': 'mutating_command',
                   'target': 'active_bitmap_leg'},
 'display_text_and_ai': {'aggregation': 'pair_all_legs_required',
                         'command': '0x4E',
                         'direction': 'phone_to_glasses_request',
                         'operation_kind': 'mutating_command',
                         'target': 'pair_left_then_right'},
 'exit_mode': {'aggregation': 'pair_all_legs_required',
               'command': '0x18',
               'direction': 'phone_to_glasses_request',
               'operation_kind': 'mutating_command',
               'target': 'pair_left_then_right'},
 'heartbeat': {'aggregation': 'pair_all_legs_required',
               'command': '0x25',
               'direction': 'phone_to_glasses_request',
               'operation_kind': 'mutating_command',
               'target': 'pair_left_then_right'},
 'microphone_data': {'aggregation': 'stream_append',
                     'command': '0xF1',
                     'direction': 'glasses_to_phone_event',
                     'operation_kind': 'stream_event',
                     'target': 'right_leg_only'},
 'microphone_on': {'aggregation': 'single_leg',
                   'command': '0x0E',
                   'direction': 'phone_to_glasses_request',
                   'operation_kind': 'mutating_command',
                   'target': 'selected_leg_default_right'},
 'notification': {'aggregation': 'single_leg_fragmented',
                  'command': '0x4B',
                  'direction': 'phone_to_glasses_request',
                  'operation_kind': 'mutating_command',
                  'target': 'left_leg'},
 'notification_whitelist': {'aggregation': 'single_leg_fragmented',
                            'command': '0x04',
                            'direction': 'phone_to_glasses_request',
                            'operation_kind': 'mutating_command',
                            'target': 'left_leg'},
 'serial_number_read': {'aggregation': 'single_leg',
                        'command': '0x34',
                        'direction': 'phone_to_glasses_request',
                        'operation_kind': 'read_query',
                        'target': 'selected_leg'},
 'touch_and_assistant_event': {'aggregation': 'event_dispatch',
                               'command': '0xF5',
                               'direction': 'glasses_to_phone_event',
                               'operation_kind': 'control_event',
                               'target': 'originating_leg'}}
EXPECTED_PROFILE_SHA256 = {'bitmap_crc': 'f1499f2d864182a6a51be0ac2247feff653d32c373d6a7623f95c35b44d66f1b',
 'bitmap_finish': '4344202c777cd4f0e3e5245b23cf15e0f0626d405926ce8ecc687bccccc018f5',
 'bitmap_packet': '3966ee8c064118a3ed2355c2525a91cd6db672b2bb5e0907dd219a3b61b250bb',
 'display_text_and_ai': 'cba7d6b2579334357dc7805916b96b5bed0e6475fd0d9638fb12a221b4467935',
 'exit_mode': '504a0d46b88f0d759e9491eae1c1b2b1815e8c582ec288b6faeb9800a631ec89',
 'heartbeat': '35d1e75ead41af6e751901413bbc25c53eefcc6913898449094acd8b89b18537',
 'microphone_data': 'bdb8ceabfa76f81ba3bee455e4fa83c89bd7d6303ec4c43ae655047fc0a96bdb',
 'microphone_on': 'ed19cb335fbd84072e92f1604798ee1bcf89211218a10857f8d99c0e825758c9',
 'notification': '337f30fdf845c0d30b739374cf41017fa445c359095a0c08e01097806aa29a7c',
 'notification_whitelist': 'fc7baf772f9f2cd03f86513825c86e99f19997367fbcc47ece94a0cd57e46a3a',
 'serial_number_read': '6ffe1c68bc00a0c80e5a0e7dc2a319b69b73dcae4721472aa28ce097ef034e1f',
 'touch_and_assistant_event': '907a1d762a5e6bb11fb8f992ea4ff7edfb04b5e3d088f2cf2e47ad386de63b45'}

ROOT = _impl.ROOT
MATRIX = _impl.MATRIX
BASE_CONTRACT = _impl.BASE_CONTRACT
G1CommandMatrixError = _impl.G1CommandMatrixError
ValidationSubject = _impl.ValidationSubject


def _subject() -> ValidationSubject:
    """Return an invocation-local subject without mutating implementation state."""
    return ValidationSubject(
        expected_matrix_sha256=EXPECTED_MATRIX_SHA256,
        expected_command_identities=copy.deepcopy(EXPECTED_COMMAND_IDENTITIES),
        expected_profile_sha256=copy.deepcopy(EXPECTED_PROFILE_SHA256),
    )


def strict_json(path: Path) -> dict[str, Any]:
    return _impl.strict_json(path)


def canonical_digest(value: Mapping[str, Any]) -> str:
    return _impl.canonical_digest(value)


def validate_document(root: Path, document: Mapping[str, Any]) -> dict[str, Any]:
    return _impl.validate_document(root, document, subject=_subject())


def validate(root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    return validate_document(root, strict_json(root / MATRIX))


def main() -> int:
    try:
        result = validate(ROOT)
    except (G1CommandMatrixError, KeyError, OSError, TypeError, ValueError) as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
