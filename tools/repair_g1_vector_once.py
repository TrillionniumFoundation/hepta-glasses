#!/usr/bin/env python3
"""One-shot repair for the exact typed LC3 consumer vector.

This helper is added only on an isolated branch and deletes itself before the
resulting commit. It does not relax any validation rule.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

MATRIX = Path("contracts/g1-command-matrix-v1.json")
WRAPPER = Path("services/qualification/g1_command_matrix.py")


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def main() -> None:
    document = json.loads(MATRIX.read_text(encoding="utf-8"))
    commands = document.get("commands")
    if not isinstance(commands, list):
        raise SystemExit("typed command list is missing")
    microphone = next(
        (
            item
            for item in commands
            if isinstance(item, dict) and item.get("id") == "microphone_data"
        ),
        None,
    )
    if not isinstance(microphone, dict):
        raise SystemExit("microphone_data profile is missing")
    examples = microphone.get("consumer_examples")
    if not isinstance(examples, list) or len(examples) != 1:
        raise SystemExit("microphone_data must have one consumer vector")
    example = examples[0]
    if not isinstance(example, dict) or example.get("name") != "lc3_frame":
        raise SystemExit("unexpected microphone_data consumer vector")

    example["bytes"] = [0xF1, 0x00, *([0x00] * 200)]
    if len(example["bytes"]) != 202:
        raise SystemExit("repair did not produce a 202-byte event")

    profile_digests = {
        str(command["id"]): digest(command)
        for command in commands
        if isinstance(command, dict) and isinstance(command.get("id"), str)
    }
    if len(profile_digests) != 12:
        raise SystemExit("typed profile inventory is not exactly 12")
    matrix_digest = digest(document)

    wrapper = WRAPPER.read_text(encoding="utf-8")
    wrapper, count = re.subn(
        r'EXPECTED_MATRIX_SHA256 = "[0-9a-f]{64}"',
        f'EXPECTED_MATRIX_SHA256 = "{matrix_digest}"',
        wrapper,
        count=1,
    )
    if count != 1:
        raise SystemExit("matrix digest binding was not unique")
    for identifier, value in sorted(profile_digests.items()):
        pattern = rf'("{re.escape(identifier)}": ")[0-9a-f]{{64}}(")'
        wrapper, count = re.subn(
            pattern,
            rf'\g<1>{value}\g<2>',
            wrapper,
            count=1,
        )
        if count != 1:
            raise SystemExit(f"profile digest binding was not unique: {identifier}")

    MATRIX.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    WRAPPER.write_text(wrapper, encoding="utf-8")
    print(
        json.dumps(
            {
                "event_bytes": len(example["bytes"]),
                "matrix_sha256": matrix_digest,
                "microphone_data_sha256": profile_digests["microphone_data"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
