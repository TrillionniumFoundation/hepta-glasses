"""Stable entry point for the typed G1 command-matrix validator.

The schema-v2 matrix was committed with one deterministic fixture defect: the
LC3 event example contains 201 zero payload bytes instead of the source-bound
200. Replacing the 1,984-line contract merely to delete one byte would make a
second large, difficult-to-review subject. This facade therefore applies one
closed JSON correction whose base digest, selector, precondition and result are
all pinned. No other normalization is permitted.

The effective contract is uniquely identified by the exact base matrix digest
plus the exact correction document. The generic validator still checks every
closed shape, command/profile digest, wire vector, source fragment and external
claim ceiling after that correction is applied.
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

BASE_MATRIX_SHA256 = "ef6df32301d99e3ca4ff2307852dd03bff558a5fa864b3531e43423c95eb875f"
CORRECTIONS = Path("contracts/g1-command-matrix-v1-corrections.json")

EXPECTED_CORRECTION: dict[str, Any] = {
    "schema_version": 1,
    "contract_id": "hepta-g1-command-matrix-v1-correction-1",
    "applies_to_canonical_sha256": BASE_MATRIX_SHA256,
    "operations": [
        {
            "op": "drop_exact_trailing_byte",
            "command_id": "microphone_data",
            "example_collection": "consumer_examples",
            "example_name": "lc3_frame",
            "expected_original_length": 203,
            "expected_prefix": [241, 0],
            "expected_payload_fill": 0,
            "drop_count": 1,
            "expected_result_length": 202,
            "reason": "source-bound LC3 events are command plus sequence plus exactly 200 payload bytes",
        }
    ],
    "claim_ceiling": (
        "This correction changes only one synthetic zero-filled golden vector. "
        "It does not change runtime bytes, vendor semantics, firmware support, "
        "physical qualification, state readback, deployment, signing or release authority."
    ),
}

# These digests bind every command other than the one profile whose example is
# corrected below. The corrected microphone-data profile and whole-document
# digests are derived from the exact base+correction pair, not from the document
# under test.
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


def canonical_digest(value: Mapping[str, Any]) -> str:
    return _impl.canonical_digest(value)


def _load_correction(root: Path) -> dict[str, Any]:
    correction = _impl.strict_json(root / CORRECTIONS)
    if correction != EXPECTED_CORRECTION:
        raise G1CommandMatrixError("G1 correction document drifted")
    return correction


def apply_pinned_correction(
    document: Mapping[str, Any],
    correction: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the sole permitted corrected contract or fail closed."""
    if canonical_digest(document) != BASE_MATRIX_SHA256:
        raise G1CommandMatrixError("G1 correction base matrix digest drifted")
    if correction != EXPECTED_CORRECTION:
        raise G1CommandMatrixError("G1 correction document drifted")

    effective = copy.deepcopy(dict(document))
    commands = effective.get("commands")
    if not isinstance(commands, list):
        raise G1CommandMatrixError("G1 correction command inventory is malformed")
    matches = [
        command
        for command in commands
        if isinstance(command, dict) and command.get("id") == "microphone_data"
    ]
    if len(matches) != 1:
        raise G1CommandMatrixError("G1 correction command selector is ambiguous")
    examples = matches[0].get("consumer_examples")
    if not isinstance(examples, list):
        raise G1CommandMatrixError("G1 correction example inventory is malformed")
    selected = [
        example
        for example in examples
        if isinstance(example, dict) and example.get("name") == "lc3_frame"
    ]
    if len(selected) != 1:
        raise G1CommandMatrixError("G1 correction example selector is ambiguous")

    operation = EXPECTED_CORRECTION["operations"][0]
    data = selected[0].get("bytes")
    if not isinstance(data, list) or any(
        isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 255
        for value in data
    ):
        raise G1CommandMatrixError("G1 correction target is not a byte vector")
    if len(data) != operation["expected_original_length"]:
        raise G1CommandMatrixError("G1 correction original vector length drifted")
    prefix = operation["expected_prefix"]
    if data[: len(prefix)] != prefix:
        raise G1CommandMatrixError("G1 correction vector prefix drifted")
    if any(
        value != operation["expected_payload_fill"]
        for value in data[len(prefix) :]
    ):
        raise G1CommandMatrixError("G1 correction vector payload is not the pinned fixture")
    if data[-operation["drop_count"] :] != [operation["expected_payload_fill"]]:
        raise G1CommandMatrixError("G1 correction trailing byte drifted")

    selected[0]["bytes"] = data[: -operation["drop_count"]]
    corrected = selected[0]["bytes"]
    if len(corrected) != operation["expected_result_length"]:
        raise G1CommandMatrixError("G1 correction result length drifted")
    if corrected[:2] != [241, 0] or len(corrected[2:]) != 200:
        raise G1CommandMatrixError("G1 correction did not produce a 200-byte LC3 payload")
    return effective


def load_raw_matrix(root: Path = ROOT) -> dict[str, Any]:
    return _impl.strict_json(root.resolve() / MATRIX)


def load_effective_matrix(root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    return apply_pinned_correction(load_raw_matrix(root), _load_correction(root))


def _synchronize_subject(root: Path) -> dict[str, Any]:
    """Bind the generic implementation to the exact effective contract."""
    baseline = load_effective_matrix(root)
    commands = baseline.get("commands")
    assert isinstance(commands, list)
    microphone = next(
        command
        for command in commands
        if isinstance(command, dict) and command.get("id") == "microphone_data"
    )
    profile_digests = dict(EXPECTED_PROFILE_SHA256)
    profile_digests["microphone_data"] = canonical_digest(microphone)

    _impl.EXPECTED_MATRIX_SHA256 = canonical_digest(baseline)
    _impl.EXPECTED_PROFILE_SHA256 = profile_digests
    _impl.EXPECTED_SOURCE_BINDINGS = EXPECTED_SOURCE_BINDINGS
    _impl.EXPECTED_SOURCE_BINDING_IDS = sorted(EXPECTED_SOURCE_BINDINGS)
    return baseline


def strict_json(path: Path) -> dict[str, Any]:
    value = _impl.strict_json(path)
    try:
        is_matrix = path.resolve() == (_ROOT / MATRIX).resolve()
    except OSError:
        is_matrix = False
    if is_matrix:
        return apply_pinned_correction(value, _load_correction(_ROOT))
    return value


def validate_document(root: Path, document: Mapping[str, Any]) -> dict[str, Any]:
    _synchronize_subject(root.resolve())
    result = _impl.validate_document(root.resolve(), document)
    result["correction_contract"] = str(CORRECTIONS)
    result["correction_operations"] = 1
    return result


def validate(root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    baseline = _synchronize_subject(root)
    result = _impl.validate_document(root, baseline)
    result["correction_contract"] = str(CORRECTIONS)
    result["correction_operations"] = 1
    return result


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
