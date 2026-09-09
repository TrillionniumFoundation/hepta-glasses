from __future__ import annotations

import hashlib
import importlib.util
import inspect
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
POLICY_TOOL = ROOT / "tools/native/dependency_update_policy.py"
PODFILE = ROOT / "ios/Podfile"
LOCKFILE = ROOT / "ios/Podfile.lock"


def _load_policy_module():
    spec = importlib.util.spec_from_file_location(
        "dependency_update_policy_raw_object_tests",
        POLICY_TOOL,
    )
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load dependency update policy module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


POLICY = _load_policy_module()
PODFILE_BYTES = PODFILE.read_bytes()
LOCKFILE_BYTES = LOCKFILE.read_bytes()


class DependencyRawObjectCustodyTests(unittest.TestCase):
    def _inspect_bytes(
        self,
        *,
        podfile: bytes = PODFILE_BYTES,
        lockfile: bytes = LOCKFILE_BYTES,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            podfile_path = root / "Podfile"
            lockfile_path = root / "Podfile.lock"
            podfile_path.write_bytes(podfile)
            lockfile_path.write_bytes(lockfile)
            with (
                patch.object(POLICY, "PODFILE", podfile_path),
                patch.object(POLICY, "LOCKFILE", lockfile_path),
            ):
                return POLICY.inspect_cocoapods()

    def test_reviewed_hashes_bind_exact_repository_bytes(self) -> None:
        self.assertEqual(
            hashlib.sha256(PODFILE_BYTES).hexdigest(),
            POLICY._APPROVED_PODFILE_SHA256,
        )
        self.assertEqual(
            hashlib.sha256(LOCKFILE_BYTES).hexdigest(),
            POLICY._APPROVED_PODFILE_LOCK_SHA256,
        )
        result = self._inspect_bytes()
        self.assertEqual(
            result["podfile_sha256"],
            POLICY._APPROVED_PODFILE_SHA256,
        )
        self.assertEqual(
            result["podfile_lock_sha256"],
            POLICY._APPROVED_PODFILE_LOCK_SHA256,
        )

    def test_identity_is_computed_from_raw_bytes_before_shape_checks(self) -> None:
        digest_source = inspect.getsource(POLICY._podfile_digest)
        self.assertNotIn("splitlines", digest_source)
        self.assertLess(
            digest_source.index("_raw_sha256(raw"),
            digest_source.index("_strict_utf8_lf_text(raw"),
        )

        inspect_source = inspect.getsource(POLICY.inspect_cocoapods)
        self.assertIn("podfile_raw = _read_bytes(PODFILE)", inspect_source)
        self.assertIn("lock_raw = _read_bytes(LOCKFILE)", inspect_source)
        self.assertNotIn("_read(PODFILE)", inspect_source)
        self.assertNotIn("_read(LOCKFILE)", inspect_source)
        self.assertLess(
            inspect_source.index(
                'lock_sha256 = _raw_sha256(lock_raw, "Podfile.lock")'
            ),
            inspect_source.index(
                '_strict_utf8_lf_text(lock_raw, "Podfile.lock")'
            ),
        )

        parser_source = inspect.getsource(POLICY._closed_lock_lines)
        self.assertNotIn("splitlines", parser_source)
        self.assertIn('text[:-1].split("\\n")', parser_source)

    def test_u2028_comment_swallow_variant_is_rejected(self) -> None:
        separator = "\u2028".encode("utf-8")
        candidate = PODFILE_BYTES.replace(b"\n", separator, 1)
        canonical_text = PODFILE_BYTES.decode("utf-8")
        candidate_text = candidate.decode("utf-8")

        # Python splitlines() hides the object movement, while ASCII-LF
        # physical lines show that the platform call is now attached to the
        # leading comment. The policy must reject before any Ruby/CocoaPods
        # semantic interpretation is possible.
        self.assertEqual(
            candidate_text.splitlines(),
            canonical_text.splitlines(),
        )
        self.assertIn(
            "platform :ios, '15.0'",
            candidate_text.split("\n", 1)[0],
        )
        self.assertNotEqual(
            hashlib.sha256(candidate).hexdigest(),
            POLICY._APPROVED_PODFILE_SHA256,
        )
        with self.assertRaises(POLICY.DependencyPolicyError):
            POLICY._podfile_digest(candidate)
        with self.assertRaises(POLICY.DependencyPolicyError):
            self._inspect_bytes(podfile=candidate)

    def test_every_python_non_lf_splitline_boundary_is_rejected(self) -> None:
        separators = {
            "cr": "\r",
            "crlf": "\r\n",
            "vertical-tab": "\v",
            "form-feed": "\f",
            "file-separator": "\x1c",
            "group-separator": "\x1d",
            "record-separator": "\x1e",
            "next-line": "\x85",
            "line-separator": "\u2028",
            "paragraph-separator": "\u2029",
        }
        for name, separator in separators.items():
            encoded = separator.encode("utf-8")
            pod_candidate = PODFILE_BYTES.replace(b"\n", encoded, 1)
            lock_candidate = LOCKFILE_BYTES.replace(b"\n", encoded, 1)
            with self.subTest(object="Podfile", separator=name):
                with self.assertRaises(POLICY.DependencyPolicyError):
                    POLICY._podfile_digest(pod_candidate)
                with self.assertRaises(POLICY.DependencyPolicyError):
                    self._inspect_bytes(podfile=pod_candidate)
            with self.subTest(object="Podfile.lock", separator=name):
                with self.assertRaises(POLICY.DependencyPolicyError):
                    POLICY.parse_cocoapods_lock(lock_candidate)
                with self.assertRaises(POLICY.DependencyPolicyError):
                    self._inspect_bytes(lockfile=lock_candidate)

    def test_c0_c1_and_unicode_format_controls_are_rejected(self) -> None:
        forbidden = [
            chr(codepoint)
            for codepoint in (
                *range(0x00, 0x0A),
                *range(0x0B, 0x20),
                *range(0x7F, 0xA0),
            )
        ] + [
            "\u200b",  # ZERO WIDTH SPACE, Cf
            "\u2060",  # WORD JOINER, Cf
            "\ufeff",  # ZERO WIDTH NO-BREAK SPACE / BOM, Cf
        ]
        for char in forbidden:
            raw = (
                b"# reviewed"
                + char.encode("utf-8")
                + b" bytes\n"
            )
            with self.subTest(codepoint=f"U+{ord(char):04X}"):
                with self.assertRaises(POLICY.DependencyPolicyError):
                    POLICY._strict_utf8_lf_text(raw, "fixture")

    def test_utf8_bom_invalid_utf8_and_terminal_lf_drift_are_rejected(
        self,
    ) -> None:
        cases = {
            "utf8-bom": b"\xef\xbb\xbf" + PODFILE_BYTES,
            "invalid-utf8": b"\xff" + PODFILE_BYTES,
            "missing-terminal-lf": PODFILE_BYTES[:-1],
            "double-terminal-lf": PODFILE_BYTES + b"\n",
        }
        for name, candidate in cases.items():
            with self.subTest(object="Podfile", case=name):
                with self.assertRaises(POLICY.DependencyPolicyError):
                    POLICY._podfile_digest(candidate)
                with self.assertRaises(POLICY.DependencyPolicyError):
                    self._inspect_bytes(podfile=candidate)

        lock_cases = {
            "utf8-bom": b"\xef\xbb\xbf" + LOCKFILE_BYTES,
            "invalid-utf8": b"\xff" + LOCKFILE_BYTES,
            "missing-terminal-lf": LOCKFILE_BYTES[:-1],
            "double-terminal-lf": LOCKFILE_BYTES + b"\n",
        }
        for name, candidate in lock_cases.items():
            with self.subTest(object="Podfile.lock", case=name):
                with self.assertRaises(POLICY.DependencyPolicyError):
                    POLICY.parse_cocoapods_lock(candidate)
                with self.assertRaises(POLICY.DependencyPolicyError):
                    self._inspect_bytes(lockfile=candidate)

    def test_raw_lock_binding_precedes_semantic_parser(self) -> None:
        changed = LOCKFILE_BYTES.replace(
            b"COCOAPODS: 1.17.0",
            b"COCOAPODS: 1.17.1",
        )
        self.assertNotEqual(
            hashlib.sha256(changed).hexdigest(),
            POLICY._APPROVED_PODFILE_LOCK_SHA256,
        )
        with self.assertRaisesRegex(
            POLICY.DependencyPolicyError,
            "raw bytes differ",
        ):
            self._inspect_bytes(lockfile=changed)


if __name__ == "__main__":
    unittest.main()