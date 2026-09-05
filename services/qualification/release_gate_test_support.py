from __future__ import annotations

from services.qualification.release_gate import ReleaseGate


class ReleaseGateFixtures:

    def source(self) -> dict[str, object]:
        return {
            "commit": "a" * 40,
            "tree": "b" * 40,
            "ci_checks": [
                {"name": "android-native", "conclusion": "success"},
                {"name": "flutter", "conclusion": "success"},
                {"name": "ios-native", "conclusion": "success"},
                {"name": "native-sanitizers", "conclusion": "success"},
                {"name": "repository-contracts", "conclusion": "success"},
                {"name": "secret-and-boundary-scan", "conclusion": "success"},
                {"name": "source-evidence", "conclusion": "success"},
            ],
            "sbom": {"sha256": "c" * 64},
            "sbom_ecosystems": [
                "android/gradle",
                "dart/pub",
                "ios/cocoapods",
                "native/vendored",
            ],
            "history_scan": {
                "sha256": "e" * 64,
                "scope": "all-fetched-refs-and-deduplicated-blobs",
                "commit_count": 2,
                "scanned_blob_count": 10,
                "finding_count": 0,
                "unscanned_blob_count": 0,
            },
            "native_sanitizer": {
                "sha256": "f" * 64,
                "passed": True,
                "lc3_cross_platform_parity": True,
            },
            "audit_contract": "authenticated-checkpoint-v3",
            "provenance": {"sha256": "d" * 64},
            "provenance_type": "unsigned-source-provenance-v1",
            "contracts_version": "2026-08-31-g7",
        }

    def authenticated_external_result(self) -> dict[str, object]:
        gaps = sorted(ReleaseGate.REQUIRED_AUTHORITY_GAPS)
        return {
            "ok": True,
            "complete_closure_policy": {
                "policy_id": ReleaseGate.EXTERNAL_POLICY_ID,
                "policy_revision": ReleaseGate.EXTERNAL_POLICY_REVISION,
            },
            "trust_registry": {
                "registry_id": "production-authorities",
                "sha256": "9" * 64,
                "external_pin_verified": True,
            },
            "candidate": {
                "repository": "TrillionniumFoundation/hepta-glasses",
                "commit": "a" * 40,
                "tree": "b" * 40,
            },
            "submitted_gaps": gaps,
            "missing_gaps": [],
            "missing_issuer_authority_classes": {},
            "acceptance": {"state": "accepted"},
            "review_set_integrity": {"verified": True},
            "all_authority_owned_gaps_closed": True,
        }
