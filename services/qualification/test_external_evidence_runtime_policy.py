from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from tools import validate_external_evidence as compatibility
from tools.external_evidence import (
    EvidenceError,
    _validate_bundle_at_for_tests,
    complete_closure,
    validate_bundle,
)
from tools.external_evidence import core as evidence_core
from tools.external_evidence import openssl_policy, signing
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

    @staticmethod
    def _generate_key_pair(root: Path) -> tuple[Path, Path]:
        private_key = root / "private.pem"
        public_key = root / "public.pem"
        environment = openssl_policy.trusted_subprocess_environment()
        subprocess.run(
            [
                "/usr/bin/openssl",
                "genpkey",
                "-algorithm",
                "ED25519",
                "-out",
                str(private_key),
            ],
            check=True,
            capture_output=True,
            env=environment,
        )
        subprocess.run(
            [
                "/usr/bin/openssl",
                "pkey",
                "-in",
                str(private_key),
                "-pubout",
                "-out",
                str(public_key),
            ],
            check=True,
            capture_output=True,
            env=environment,
        )
        return private_key, public_key

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

    def test_core_resolver_pins_root_owned_absolute_system_binary(self) -> None:
        resolved = evidence_core._resolve_openssl("openssl")
        self.assertEqual(resolved, "/usr/bin/openssl")
        state = os.lstat(resolved)
        self.assertTrue(stat.S_ISREG(state.st_mode))
        self.assertEqual(state.st_uid, 0)
        self.assertFalse(state.st_mode & (stat.S_IWGRP | stat.S_IWOTH))
        with self.assertRaisesRegex(
            EvidenceError,
            "custom OpenSSL executable selection is prohibited",
        ):
            evidence_core._resolve_openssl("/tmp/attacker-openssl")

    def test_trusted_environment_drops_loader_and_openssl_overrides(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "PATH": "/tmp/attacker-bin",
                "OPENSSL_CONF": "/tmp/attacker.cnf",
                "OPENSSL_MODULES": "/tmp/attacker-modules",
                "LD_PRELOAD": "/tmp/attacker.so",
                "DYLD_INSERT_LIBRARIES": "/tmp/attacker.dylib",
            },
            clear=False,
        ):
            environment = openssl_policy.trusted_subprocess_environment()
        self.assertEqual(environment["PATH"], "/usr/bin:/bin")
        self.assertEqual(environment["OPENSSL_CONF"], "/dev/null")
        for prohibited in (
            "OPENSSL_MODULES",
            "LD_PRELOAD",
            "DYLD_INSERT_LIBRARIES",
        ):
            self.assertNotIn(prohibited, environment)

    def test_proxy_rejects_positional_popen_options(self) -> None:
        with self.assertRaisesRegex(
            EvidenceError,
            "positional subprocess options are prohibited",
        ):
            evidence_core.subprocess.run(
                ["openssl", "version"],
                -1,
                "/tmp/attacker-executable",
            )

    def test_proxy_rejects_execution_context_keywords(self) -> None:
        cases = (
            ({"env": {}}, "caller-supplied subprocess environment"),
            ({"executable": "/tmp/attacker-executable"}, "executable override"),
            ({"shell": True}, "shell execution"),
            ({"cwd": "/tmp"}, "unsupported OpenSSL subprocess options"),
            ({"preexec_fn": lambda: None}, "unsupported OpenSSL subprocess options"),
            ({"pass_fds": (2,)}, "unsupported OpenSSL subprocess options"),
        )
        for kwargs, message in cases:
            with self.subTest(kwargs=tuple(kwargs)):
                with self.assertRaisesRegex(EvidenceError, message):
                    evidence_core.subprocess.run(
                        ["openssl", "version"],
                        **kwargs,
                    )

    def test_proxy_rejects_binary_and_nul_command_arguments(self) -> None:
        with self.assertRaisesRegex(
            EvidenceError,
            "argument 0 must be text",
        ):
            evidence_core.subprocess.run([b"openssl", b"version"])
        with self.assertRaisesRegex(
            EvidenceError,
            "argument 1 contains NUL",
        ):
            evidence_core.subprocess.run(["openssl", "version\x00ignored"])

    def test_signing_and_verification_ignore_path_shadow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            private_key, public_key = self._generate_key_pair(root)
            shadow = root / "shadow"
            shadow.mkdir()
            marker = root / "attacker-executed"
            fake = shadow / "openssl"
            fake.write_text(
                "#!/bin/sh\nprintf attacker > " + str(marker) + "\nexit 0\n",
                encoding="utf-8",
            )
            fake.chmod(0o755)

            payload = b"trusted absolute OpenSSL path"
            with mock.patch.dict(
                os.environ,
                {
                    "PATH": str(shadow),
                    "OPENSSL_CONF": str(root / "attacker.cnf"),
                    "OPENSSL_MODULES": str(root / "attacker-modules"),
                },
                clear=False,
            ):
                signature = signing.sign_ed25519(private_key, payload)
                compatibility.verify_ed25519(
                    public_key.read_text(encoding="utf-8"),
                    payload,
                    signature,
                    label="trusted-openssl-path-test",
                )

            self.assertEqual(len(signature), 64)
            self.assertFalse(marker.exists())

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

    def test_private_test_hook_rejects_missing_or_naive_time(self) -> None:
        with self.assertRaisesRegex(
            TypeError,
            "requires a datetime now",
        ):
            _validate_bundle_at_for_tests(
                Path("unused-bundle.json"),
                **self._arguments(),
                now=None,
            )
        with self.assertRaisesRegex(
            TypeError,
            "requires timezone-aware now",
        ):
            _validate_bundle_at_for_tests(
                Path("unused-bundle.json"),
                **self._arguments(),
                now=datetime(2026, 9, 2, 12, 0),
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
