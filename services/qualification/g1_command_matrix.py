"""Stable entry point for the typed G1 command matrix validator.

The implementation is retained in ``g1_command_matrix_impl`` so the typed
contract digest can be reviewed independently from the generic closed-shape,
wire-vector and source-binding validation machinery.  The facade deliberately
synchronizes the few immutable subject digests before every call; this also
preserves the hostile tests that temporarily replace EXPECTED_SOURCE_BINDINGS.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Mapping

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from services.qualification import g1_command_matrix_impl as _impl

EXPECTED_MATRIX_SHA256 = "900deb5e601bcce7a6ac0241d3e4bab37dce8659a6d40f9fb3bfa4e47e9fec17"
EXPECTED_PROFILE_SHA256 = {
    "bitmap_crc": "d8b30592c04ce8f0c59f835570172b099ea15d4d5fb69e47abcec7e514baaedb",
    "bitmap_finish": "1c842279ad7f6426b16b00cd704abc26e85604c4139bf88624613b803a0507b5",
    "bitmap_packet": "26f99341059b2d5e2c96305f35b932bd947722595e5868ed8d751f810afa484d",
    "display_text_and_ai": "cebca2396be7f0191f56be6881bc176109ed4b5ddb7d20b2a70f5a8064deb8f8",
    "exit_mode": "eb99cbc88378df2e65be1ae7d2dc27359529fcb309864a4df05c77a7669958cd",
    "heartbeat": "24c4c037ce94821fdaca743d962bc0065f78ac3f5e72eb0941fe4dbb9a05961e",
    "microphone_data": "06b70494f7e3a9f14bb091e22bff7aebffd4346ba6662fbc0b26e08c5bd2dea5",
    "microphone_on": "c9afee97e64e5567aa837e473976ba81e4da32b410cd822fac4cf3236bf920f4",
    "notification": "8bbebaf47c7c56ffc006062e5c7643f9858e5043d2c5548377f51632c5867e6a",
    "notification_whitelist": "82217fdde7eb9ac110e9b20a89da3ceaf34d97d9edd252fd2263591ccdb727cd",
    "serial_number_read": "2351779011cdd202d982b365093bbfcd9ccbca1924c5d33704db0ae2214c3537",
    "touch_and_assistant_event": "e50e44989b13d6489bc6f90585a7476428434381f4ed624d2ceba09fca51bb0c",
}

ROOT = _impl.ROOT
MATRIX = _impl.MATRIX
BASE_CONTRACT = _impl.BASE_CONTRACT
G1CommandMatrixError = _impl.G1CommandMatrixError
EXPECTED_SOURCE_BINDINGS = _impl.EXPECTED_SOURCE_BINDINGS
EXPECTED_COMMAND_IDENTITIES = _impl.EXPECTED_COMMAND_IDENTITIES


def _synchronize_subject() -> None:
    """Bind the generic implementation to this exact reviewed matrix subject."""
    _impl.EXPECTED_MATRIX_SHA256 = EXPECTED_MATRIX_SHA256
    _impl.EXPECTED_PROFILE_SHA256 = EXPECTED_PROFILE_SHA256
    _impl.EXPECTED_SOURCE_BINDINGS = EXPECTED_SOURCE_BINDINGS
    _impl.EXPECTED_SOURCE_BINDING_IDS = sorted(EXPECTED_SOURCE_BINDINGS)


def strict_json(path: Path) -> dict[str, Any]:
    return _impl.strict_json(path)


def canonical_digest(value: Mapping[str, Any]) -> str:
    return _impl.canonical_digest(value)


def validate_document(root: Path, document: Mapping[str, Any]) -> dict[str, Any]:
    _synchronize_subject()
    return _impl.validate_document(root, document)


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
