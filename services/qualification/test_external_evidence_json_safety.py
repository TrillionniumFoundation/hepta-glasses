from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.external_evidence.core import EvidenceError, read_object, require_string


class ExternalEvidenceJsonSafetyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def _write(self, text: str) -> Path:
        path = self.root / "document.json"
        path.write_text(text, encoding="utf-8")
        return path

    def test_duplicate_top_level_member_is_rejected(self) -> None:
        path = self._write('{"contract_id":"first","contract_id":"second"}')
        with self.assertRaisesRegex(
            EvidenceError,
            "duplicate JSON object member.*contract_id",
        ):
            read_object(path, "bundle")

    def test_duplicate_nested_member_is_rejected(self) -> None:
        path = self._write(
            '{"issuer":{"identity":"trusted","identity":"substituted"}}'
        )
        with self.assertRaisesRegex(
            EvidenceError,
            "duplicate JSON object member.*identity",
        ):
            read_object(path, "bundle")

    def test_leading_or_trailing_whitespace_is_not_silently_normalized(self) -> None:
        for value in (" reviewer", "reviewer ", "\treviewer", "reviewer\n"):
            with self.subTest(value=repr(value)):
                with self.assertRaisesRegex(
                    EvidenceError,
                    "leading or trailing whitespace",
                ):
                    require_string(value, label="reviewer.identity")

    def test_exact_string_is_preserved(self) -> None:
        self.assertEqual(
            require_string("reviewer", label="reviewer.identity"),
            "reviewer",
        )


if __name__ == "__main__":
    unittest.main()
