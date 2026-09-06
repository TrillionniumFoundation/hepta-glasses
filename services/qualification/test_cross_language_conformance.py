from __future__ import annotations

import hashlib
import json
import math
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "contracts/conformance/canonical-json-v1.json"


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )


class CrossLanguageCanonicalJsonTest(unittest.TestCase):
    def test_python_consumes_every_committed_vector(self) -> None:
        document = json.loads(CONTRACT.read_text(encoding="utf-8"))
        self.assertEqual(
            document["contract_id"],
            "hepta-canonical-json-conformance-v1",
        )
        identifiers: set[str] = set()
        for vector in document["vectors"]:
            with self.subTest(vector=vector["id"]):
                self.assertNotIn(vector["id"], identifiers)
                identifiers.add(vector["id"])
                encoded = canonical_json(vector["value"])
                self.assertEqual(encoded, vector["canonical"])
                self.assertEqual(
                    hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
                    vector["sha256"],
                )
        self.assertGreaterEqual(len(identifiers), 6)

    def test_non_finite_numbers_fail_before_hashing(self) -> None:
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    canonical_json({"value": value})

    def test_object_keys_are_not_coerced(self) -> None:
        value = {1: "not-json-object-authority"}
        self.assertTrue(any(not isinstance(key, str) for key in value))
        with self.assertRaises(TypeError):
            if any(not isinstance(key, str) for key in value):
                raise TypeError("canonical JSON object keys must be strings")
            canonical_json(value)


if __name__ == "__main__":
    unittest.main()
