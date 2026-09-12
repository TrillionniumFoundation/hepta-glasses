from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
import warnings
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from tools import verify_source_archive_receipt as archive_verifier
from tools.verify_source_archive_receipt import (
    ArchiveReceiptError,
    EXPECTED_CI_CHECKS,
    EXPECTED_ECOSYSTEMS,
    EXPECTED_GATE_CHECKS,
    EXPECTED_MEMBERS,
    verify_archive_receipt,
)

HEAD = "a" * 40
TREE = "b" * 40
KEY_ID = "archive-security-2026-01"
VERIFY_TIME = datetime(2026, 9, 10, 0, 0, 0, tzinfo=timezone.utc)


@unittest.skipUnless(
    Path("/usr/bin/openssl").is_file(),
    "fixed system OpenSSL is required",
)
class SourceArtifactArchiveReceiptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="hepta-archive-test-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.repository = self.directory / "repository"
        self.external = self.directory / "external"
        self.repository.mkdir()
        self.external.mkdir()
        self.private_key = self.external / "private.pem"
        self.public_key = self.external / "public.pem"
        subprocess.run(
            [
                "/usr/bin/openssl",
                "genpkey",
                "-algorithm",
                "Ed25519",
                "-out",
                str(self.private_key),
            ],
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
        )
        subprocess.run(
            [
                "/usr/bin/openssl",
                "pkey",
                "-in",
                str(self.private_key),
                "-pubout",
                "-out",
                str(self.public_key),
            ],
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
        )
        self.artifact = self.external / f"hepta-source-evidence-{HEAD}.zip"
        self.receipt = self.external / "receipt.json"
        self.registry = self.external / "trust-registry.json"
        self.history = {
            "head": HEAD,
            "scope": "all-fetched-refs-and-deduplicated-blobs",
            "commit_count": 9,
            "scanned_blob_count": 100,
            "raw_finding_count": 2,
            "acknowledged_finding_count": 2,
            "finding_count": 0,
            "unused_acknowledgement_count": 0,
            "unscanned_blob_count": 0,
        }
        self.native = {
            "passed": True,
            "lc3_cross_platform_parity": True,
            "asan": True,
            "ubsan": True,
        }
        self.sbom = self._sbom()
        self.gate = {
            "checks": {name: True for name in sorted(EXPECTED_GATE_CHECKS)},
            "missing": [],
            "mode": "source",
            "passed": True,
        }
        self._write_registry()
        self._write_canonical_archive()
        self._write_signed_receipt()

    @staticmethod
    def _json_bytes(value: object) -> bytes:
        return (
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )

    @staticmethod
    def _sha(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def _sbom(self) -> dict[str, object]:
        files = [
            {
                "SPDXID": "SPDXRef-File-1-README.md",
                "checksums": [{"algorithm": "SHA256", "checksumValue": "c" * 64}],
                "fileName": "README.md",
                "licenseConcluded": "NOASSERTION",
            }
        ]
        packages = [
            {
                "SPDXID": "SPDXRef-Package-HeptaGlasses",
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": True,
                "licenseConcluded": "BSD-2-Clause",
                "licenseDeclared": "BSD-2-Clause",
                "name": "hepta-glasses",
                "supplier": "Organization: Trillionnium Foundation",
                "versionInfo": "0.2.0+2",
                "comment": "ecosystem=application",
            }
        ]
        for index, ecosystem in enumerate(sorted(EXPECTED_ECOSYSTEMS), start=1):
            packages.append(
                {
                    "SPDXID": f"SPDXRef-Package-{index}",
                    "downloadLocation": "NOASSERTION",
                    "filesAnalyzed": False,
                    "licenseConcluded": "NOASSERTION",
                    "licenseDeclared": "NOASSERTION",
                    "name": f"dependency-{index}",
                    "supplier": "NOASSERTION",
                    "versionInfo": "1.0.0",
                    "comment": f"ecosystem={ecosystem}",
                }
            )
        return {
            "SPDXID": "SPDXRef-DOCUMENT",
            "creationInfo": {"creators": ["Tool: hepta-source-sbom-2"]},
            "dataLicense": "CC0-1.0",
            "documentDescribes": ["SPDXRef-Package-HeptaGlasses"],
            "documentNamespace": (
                f"urn:hepta:sbom:TrillionniumFoundation/hepta-glasses:{HEAD}"
            ),
            "files": files,
            "name": f"TrillionniumFoundation/hepta-glasses@{HEAD}",
            "packages": packages,
            "relationships": [],
            "spdxVersion": "SPDX-2.3",
        }

    def _payloads(self) -> dict[str, bytes]:
        history_bytes = self._json_bytes(self.history)
        native_bytes = self._json_bytes(self.native)
        sbom_bytes = self._json_bytes(self.sbom)
        provenance = {
            "type": "unsigned-source-provenance-v1",
            "attestation": "unsigned-ci-generated-source-metadata",
            "builder": "github-actions/hepta-source-evidence-v3",
            "commit": HEAD,
            "contracts_version": "2026-09-01-g8",
            "generated_at": "2026-09-09T00:00:00+00:00",
            "history_scan_digest": self._sha(history_bytes),
            "native_sanitizer_digest": self._sha(native_bytes),
            "repository": "TrillionniumFoundation/hepta-glasses",
            "sbom_digest": self._sha(sbom_bytes),
            "tree": TREE,
        }
        provenance_bytes = self._json_bytes(provenance)
        source = {
            "audit_contract": "authenticated-checkpoint-v3",
            "ci_checks": [
                {"name": name, "conclusion": "success"}
                for name in EXPECTED_CI_CHECKS
            ],
            "commit": HEAD,
            "contracts_version": "2026-09-01-g8",
            "history_scan": {
                "sha256": self._sha(history_bytes),
                "scope": self.history["scope"],
                "commit_count": self.history["commit_count"],
                "scanned_blob_count": self.history["scanned_blob_count"],
                "raw_finding_count": self.history["raw_finding_count"],
                "acknowledged_finding_count": self.history[
                    "acknowledged_finding_count"
                ],
                "finding_count": self.history["finding_count"],
                "unused_acknowledgement_count": self.history[
                    "unused_acknowledgement_count"
                ],
                "unscanned_blob_count": self.history["unscanned_blob_count"],
            },
            "native_sanitizer": {
                "sha256": self._sha(native_bytes),
                "passed": self.native["passed"],
                "lc3_cross_platform_parity": self.native[
                    "lc3_cross_platform_parity"
                ],
            },
            "provenance": {"sha256": self._sha(provenance_bytes)},
            "provenance_type": provenance["type"],
            "sbom": {"sha256": self._sha(sbom_bytes)},
            "sbom_ecosystems": sorted(EXPECTED_ECOSYSTEMS),
            "tree": TREE,
        }
        release_bytes = self._json_bytes({"source": source})
        summary = {
            "audit_contract": "authenticated-checkpoint-v3",
            "commit": HEAD,
            "contracts_version": "2026-09-01-g8",
            "file_count": len(self.sbom["files"]),
            "history_commit_count": self.history["commit_count"],
            "history_raw_finding_count": self.history["raw_finding_count"],
            "history_acknowledged_finding_count": self.history[
                "acknowledged_finding_count"
            ],
            "history_finding_count": self.history["finding_count"],
            "history_unused_acknowledgement_count": self.history[
                "unused_acknowledgement_count"
            ],
            "history_unscanned_blob_count": self.history[
                "unscanned_blob_count"
            ],
            "native_sanitizer_digest": self._sha(native_bytes),
            "package_count": len(self.sbom["packages"]),
            "provenance_digest": self._sha(provenance_bytes),
            "sbom_digest": self._sha(sbom_bytes),
            "sbom_ecosystems": sorted(EXPECTED_ECOSYSTEMS),
            "tree": TREE,
        }
        return {
            "source-evidence-summary.json": self._json_bytes(summary),
            "source-gate-result.json": self._json_bytes(self.gate),
            "source-history-scan.json": history_bytes,
            "source-native-sanitizer.json": native_bytes,
            "source-provenance.json": provenance_bytes,
            "source-release-bundle.json": release_bytes,
            "source-sbom.spdx.json": sbom_bytes,
        }

    def _write_archive_from_entries(
        self,
        entries: list[tuple[zipfile.ZipInfo | str, bytes]],
    ) -> None:
        with zipfile.ZipFile(
            self.artifact,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
        ) as archive:
            for name_or_info, data in entries:
                archive.writestr(name_or_info, data)

    def _write_canonical_archive(self) -> None:
        payloads = self._payloads()
        self._write_archive_from_entries(
            [(name, payloads[name]) for name in EXPECTED_MEMBERS]
        )

    def _write_registry(self, *, status_value: str = "active") -> None:
        self.registry.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "keys": [
                        {
                            "key_id": KEY_ID,
                            "algorithm": "ed25519",
                            "public_key_pem": self.public_key.read_text(
                                encoding="utf-8"
                            ),
                            "status": status_value,
                            "valid_from": "2026-01-01T00:00:00Z",
                            "valid_until": "2030-01-01T00:00:00Z",
                        }
                    ],
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )

    def _unsigned_receipt(self) -> dict[str, object]:
        data = self.artifact.read_bytes()
        digest = self._sha(data)
        return {
            "schema_version": 1,
            "repository": "TrillionniumFoundation/hepta-glasses",
            "head_commit": HEAD,
            "source_tree": TREE,
            "artifact_name": f"hepta-source-evidence-{HEAD}",
            "artifact_sha256": digest,
            "artifact_size_bytes": len(data),
            "archive_object": f"sha256:{digest}",
            "archived_at": "2026-09-09T01:00:00Z",
            "retention_until": "2030-09-09T01:00:00Z",
            "custodian": "independent archive security",
            "key_id": KEY_ID,
        }

    def _write_signed_receipt(self, mutate=None) -> None:
        unsigned = self._unsigned_receipt()
        if mutate is not None:
            mutate(unsigned)
        payload = self.external / "payload.bin"
        signature = self.external / "signature.bin"
        payload.write_bytes(archive_verifier._canonical_json(unsigned))
        subprocess.run(
            [
                "/usr/bin/openssl",
                "pkeyutl",
                "-sign",
                "-inkey",
                str(self.private_key),
                "-rawin",
                "-in",
                str(payload),
                "-out",
                str(signature),
            ],
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
        )
        receipt = dict(unsigned)
        receipt["signature"] = base64.b64encode(
            signature.read_bytes()
        ).decode("ascii")
        self.receipt.write_text(
            json.dumps(receipt, sort_keys=True),
            encoding="utf-8",
        )

    def _verify(
        self,
        *,
        registry: Path | None = None,
        verification_time: datetime = VERIFY_TIME,
    ):
        return verify_archive_receipt(
            receipt_path=self.receipt,
            artifact_path=self.artifact,
            trust_registry_path=registry or self.registry,
            repository_root=self.repository,
            verification_time=verification_time,
            expected_head=HEAD,
            expected_tree=TREE,
        )

    def test_valid_external_content_addressed_archive_passes(self) -> None:
        result = self._verify()
        self.assertEqual(result.head_commit, HEAD)
        self.assertEqual(result.source_tree, TREE)
        self.assertEqual(result.member_count, 7)
        self.assertEqual(result.source_gate_check_count, 17)
        self.assertEqual(result.sbom_file_count, 1)
        self.assertEqual(result.sbom_package_count, 5)

    def test_future_dated_receipt_is_rejected(self) -> None:
        self._write_signed_receipt(
            lambda value: value.__setitem__(
                "archived_at", "2026-09-11T00:00:00Z"
            )
        )
        with self.assertRaisesRegex(ArchiveReceiptError, "future-dated"):
            self._verify()

    def test_expired_retention_is_rejected(self) -> None:
        self._write_signed_receipt(
            lambda value: value.__setitem__(
                "retention_until", "2026-09-09T12:00:00Z"
            )
        )
        with self.assertRaisesRegex(ArchiveReceiptError, "retention has expired"):
            self._verify()

    def test_trusted_time_must_be_explicit_utc_seconds(self) -> None:
        with self.assertRaisesRegex(ArchiveReceiptError, "timezone-aware UTC"):
            self._verify(verification_time=datetime(2026, 9, 10))
        with self.assertRaisesRegex(ArchiveReceiptError, "whole-second"):
            self._verify(
                verification_time=datetime(
                    2026, 9, 10, 0, 0, 0, 1, tzinfo=timezone.utc
                )
            )

    def test_artifact_byte_tampering_is_rejected(self) -> None:
        self.artifact.write_bytes(self.artifact.read_bytes() + b"tamper")
        with self.assertRaisesRegex(ArchiveReceiptError, "SHA-256"):
            self._verify()

    def test_missing_member_is_rejected(self) -> None:
        payloads = self._payloads()
        self._write_archive_from_entries(
            [(name, payloads[name]) for name in EXPECTED_MEMBERS[:-1]]
        )
        self._write_signed_receipt()
        with self.assertRaisesRegex(ArchiveReceiptError, "exactly seven"):
            self._verify()

    def test_extra_member_is_rejected(self) -> None:
        payloads = self._payloads()
        entries = [(name, payloads[name]) for name in EXPECTED_MEMBERS]
        entries.append(("extra.json", b"{}\n"))
        self._write_archive_from_entries(entries)
        self._write_signed_receipt()
        with self.assertRaisesRegex(ArchiveReceiptError, "exactly seven"):
            self._verify()

    def test_unsafe_member_path_is_rejected(self) -> None:
        payloads = self._payloads()
        entries = [(name, payloads[name]) for name in EXPECTED_MEMBERS[:-1]]
        entries.append(("../source-sbom.spdx.json", payloads[EXPECTED_MEMBERS[-1]]))
        self._write_archive_from_entries(entries)
        self._write_signed_receipt()
        with self.assertRaisesRegex(ArchiveReceiptError, "unsafe member path"):
            self._verify()

    def test_duplicate_member_is_rejected(self) -> None:
        payloads = self._payloads()
        entries = [(name, payloads[name]) for name in EXPECTED_MEMBERS[:-1]]
        entries.append((EXPECTED_MEMBERS[0], payloads[EXPECTED_MEMBERS[0]]))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            self._write_archive_from_entries(entries)
        self._write_signed_receipt()
        with self.assertRaisesRegex(ArchiveReceiptError, "duplicate member"):
            self._verify()

    def test_symlink_member_is_rejected(self) -> None:
        payloads = self._payloads()
        entries: list[tuple[zipfile.ZipInfo | str, bytes]] = []
        for name in EXPECTED_MEMBERS:
            if name == "source-sbom.spdx.json":
                info = zipfile.ZipInfo(name)
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                entries.append((info, b"target"))
            else:
                entries.append((name, payloads[name]))
        self._write_archive_from_entries(entries)
        self._write_signed_receipt()
        with self.assertRaisesRegex(ArchiveReceiptError, "symlink or special"):
            self._verify()

    def test_compression_bomb_ratio_is_rejected(self) -> None:
        payloads = self._payloads()
        payloads["source-sbom.spdx.json"] = b"0" * (2 * 1024 * 1024)
        self._write_archive_from_entries(
            [(name, payloads[name]) for name in EXPECTED_MEMBERS]
        )
        self._write_signed_receipt()
        with self.assertRaisesRegex(ArchiveReceiptError, "compression-ratio"):
            self._verify()

    def test_truncated_zip_is_rejected_even_when_receipt_is_resigned(self) -> None:
        data = self.artifact.read_bytes()
        self.artifact.write_bytes(data[:-16])
        self._write_signed_receipt()
        with self.assertRaisesRegex(ArchiveReceiptError, "valid ZIP"):
            self._verify()

    def test_internal_summary_identity_drift_is_rejected(self) -> None:
        payloads = self._payloads()
        summary = json.loads(payloads["source-evidence-summary.json"])
        summary["commit"] = "d" * 40
        payloads["source-evidence-summary.json"] = self._json_bytes(summary)
        self._write_archive_from_entries(
            [(name, payloads[name]) for name in EXPECTED_MEMBERS]
        )
        self._write_signed_receipt()
        with self.assertRaisesRegex(ArchiveReceiptError, "summary.*head/tree"):
            self._verify()

    def test_failed_source_gate_is_rejected(self) -> None:
        self.gate["checks"]["required_ci"] = False
        self.gate["missing"] = ["required_ci"]
        self.gate["passed"] = False
        self._write_canonical_archive()
        self._write_signed_receipt()
        with self.assertRaisesRegex(ArchiveReceiptError, "did not pass"):
            self._verify()

    def test_non_spdx_sbom_is_rejected_with_cross_digests_updated(self) -> None:
        self.sbom["spdxVersion"] = "SPDX-2.2"
        self._write_canonical_archive()
        self._write_signed_receipt()
        with self.assertRaisesRegex(ArchiveReceiptError, "not SPDX 2.3"):
            self._verify()

    def test_history_findings_are_rejected_with_cross_digests_updated(self) -> None:
        self.history["finding_count"] = 1
        self._write_canonical_archive()
        self._write_signed_receipt()
        with self.assertRaisesRegex(ArchiveReceiptError, "summary reports"):
            self._verify()

    def test_internal_duplicate_json_key_is_rejected(self) -> None:
        payloads = self._payloads()
        payloads["source-native-sanitizer.json"] = (
            b'{"passed":true,"passed":true,"lc3_cross_platform_parity":true}\n'
        )
        self._write_archive_from_entries(
            [(name, payloads[name]) for name in EXPECTED_MEMBERS]
        )
        self._write_signed_receipt()
        with self.assertRaisesRegex(ArchiveReceiptError, "duplicate JSON key"):
            self._verify()

    def test_inactive_key_is_rejected(self) -> None:
        self._write_registry(status_value="revoked")
        with self.assertRaisesRegex(ArchiveReceiptError, "not active"):
            self._verify()

    def test_repository_contained_trust_registry_is_rejected(self) -> None:
        inside = self.repository / "trust.json"
        inside.write_bytes(self.registry.read_bytes())
        with self.assertRaisesRegex(ArchiveReceiptError, "outside the repository"):
            self._verify(registry=inside)

    def test_modified_signed_receipt_is_rejected(self) -> None:
        receipt = json.loads(self.receipt.read_text(encoding="utf-8"))
        receipt["custodian"] = "attacker"
        self.receipt.write_text(json.dumps(receipt), encoding="utf-8")
        with self.assertRaisesRegex(ArchiveReceiptError, "signature verification"):
            self._verify()

    def test_receipt_shape_is_closed(self) -> None:
        receipt = json.loads(self.receipt.read_text(encoding="utf-8"))
        receipt["unreviewed_authority"] = True
        self.receipt.write_text(json.dumps(receipt), encoding="utf-8")
        with self.assertRaisesRegex(ArchiveReceiptError, "keys are not closed"):
            self._verify()

    def test_bool_is_not_artifact_size(self) -> None:
        self._write_signed_receipt(
            lambda value: value.__setitem__("artifact_size_bytes", True)
        )
        with self.assertRaisesRegex(ArchiveReceiptError, "integer"):
            self._verify()

    def test_duplicate_receipt_json_key_is_rejected(self) -> None:
        self.receipt.write_text(
            '{"schema_version":1,"schema_version":1}',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ArchiveReceiptError, "duplicate JSON key"):
            self._verify()

    def test_fixed_openssl_path_cannot_be_replaced_by_path(self) -> None:
        fake = self.external / "openssl"
        fake.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        fake.chmod(0o755)
        with mock.patch.object(archive_verifier, "OPENSSL_PATH", fake):
            with self.assertRaisesRegex(ArchiveReceiptError, "fixed system OpenSSL"):
                self._verify()


if __name__ == "__main__":
    unittest.main()
