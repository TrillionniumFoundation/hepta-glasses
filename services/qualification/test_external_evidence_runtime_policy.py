from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path

from tools import validate_external_evidence as compatibility
from tools.external_evidence import (
    EvidenceError,
    _validate_bundle_at_for_tests,
    complete_closure,
    validate_bundle,
)
from tools.external_evidence.cli import parse_args


class ExternalEvidenceRuntimePolicyTest(unittest.TestCase):
    @staticmethod
    def _arguments() -> dict[str, object]:
        return {
            "artifact_root": Path("unused-artifacts"),
            "expected_commit": None,
            "expected_tree": None,
            "require_complete": False,
            "require_accepted": False,
            "trust_registry_path": None,
            "expected_trust_registry_sha256": None,
        }

    def test_public_package_rejects_caller_supplied_clock(self) -> None:
        with self.assertRaisesRegex(
            EvidenceError,
            "caller-supplied validation time is prohibited",
        ):
            validate_bundle(
                Path("unused-bundle.json"),
                **self._arguments(),
                now=datetime(2000, 1, 1, tzinfo=timezone.utc),
            )

    def test_direct_policy_module_uses_the_same_clock_boundary(self) -> None:
        self.assertIs(validate_bundle, complete_closure.validate_bundle)
        with self.assertRaisesRegex(
            EvidenceError,
            "caller-supplied validation time is prohibited",
        ):
            complete_closure.validate_bundle(
                Path("unused-bundle.json"),
                **self._arguments(),
                now=datetime(2000, 1, 1, tzinfo=timezone.utc),
            )

    def test_public_validator_rejects_custom_openssl_selection(self) -> None:
        with self.assertRaisesRegex(
            EvidenceError,
            "custom OpenSSL executable selection is prohibited",
        ):
            validate_bundle(
                Path("unused-bundle.json"),
                **self._arguments(),
                openssl_binary="/tmp/attacker-openssl",
            )

    def test_private_test_hook_accepts_only_an_explicit_fixed_clock(self) -> None:
        with self.assertRaisesRegex(
            EvidenceError,
            "missing or unreadable|references a missing|cannot be opened",
        ):
            _validate_bundle_at_for_tests(
                Path("unused-bundle.json"),
                **self._arguments(),
                now=datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc),
            )
        with self.assertRaisesRegex(
            EvidenceError,
            "custom OpenSSL executable selection is prohibited",
        ):
            _validate_bundle_at_for_tests(
                Path("unused-bundle.json"),
                **self._arguments(),
                now=datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc),
                openssl_binary="/tmp/attacker-openssl",
            )

    def test_executable_cli_has_no_crypto_binary_override(self) -> None:
        with self.assertRaises(SystemExit):
            parse_args(
                [
                    "--bundle",
                    "bundle.json",
                    "--artifact-root",
                    "artifacts",
                    "--trust-registry",
                    "trust-registry.json",
                    "--expected-trust-registry-sha256",
                    "0" * 64,
                    "--openssl-binary",
                    "/tmp/attacker-openssl",
                ]
            )

    def test_compatibility_helper_rejects_custom_openssl(self) -> None:
        with self.assertRaisesRegex(
            EvidenceError,
            "custom OpenSSL executable selection is prohibited",
        ):
            compatibility.verify_ed25519(
                "-----BEGIN PUBLIC KEY-----\ninvalid\n-----END PUBLIC KEY-----\n",
                b"message",
                b"0" * 64,
                label="runtime-policy-test",
                openssl_binary="/tmp/attacker-openssl",
            )


if __name__ == "__main__":
    unittest.main()
