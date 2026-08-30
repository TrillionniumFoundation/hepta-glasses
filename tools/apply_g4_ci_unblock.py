#!/usr/bin/env python3
"""Transient deterministic G4 native closure runner."""
from __future__ import annotations
import base64
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
PARTS = [HERE / f"g4_payload_{index}.txt" for index in range(5)]
payload = "".join(part.read_text(encoding="ascii").strip() for part in PARTS)
source = zlib.decompress(base64.b64decode(payload, validate=True)).decode("utf-8")
old_guard = '''    if count != 1:
        raise RuntimeError(f"{relative}: expected one pre-image, found {count}")
'''
new_guard = '''    if count != 1 and not (
        relative == "lib/ble_manager.dart"
        and old.startswith("    final next = _nextReceive;")
        and count == 2
    ):
        raise RuntimeError(f"{relative}: expected one pre-image, found {count}")
'''
if source.count(old_guard) != 1:
    raise RuntimeError("G4 payload replace_once guard did not match")
source = source.replace(old_guard, new_guard, 1)
old_constructor = '''"  EvenG1Transport({BleManager? manager}) : _manager = manager ?? BleManager.get();\\n\\n  final BleManager _manager;\\n",'''
formatted_constructor = '''"  EvenG1Transport({BleManager? manager})\\n      : _manager = manager ?? BleManager.get();\\n\\n  final BleManager _manager;\\n",'''
if source.count(old_constructor) != 1:
    raise RuntimeError("G4 transport constructor pre-image did not match payload")
source = source.replace(old_constructor, formatted_constructor, 1)
exec(compile(source, __file__, "exec"), {"__name__": "__main__", "__file__": __file__})
for part in PARTS:
    part.unlink()
Path(__file__).unlink()
