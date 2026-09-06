from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

from tools.external_evidence import acceptance
from tools.external_evidence import complete_closure
from tools.external_evidence.core import _READ_SNAPSHOT


class _ReadProbe(Exception):
    """Stop validation after observing the active snapshot transaction."""


class ExternalEvidenceEntrypointSnapshotTest(unittest.TestCase):
    def test_direct_policy_entrypoint_owns_the_validation_snapshot(self) -> None:
        original_read_object = complete_closure.read_object
        observed: list[bool] = []

        def probe_read_object(*args: Any, **kwargs: Any) -> dict[str, Any]:
            del args, kwargs
            observed.append(_READ_SNAPSHOT.get() is not None)
            raise _ReadProbe

        complete_closure.read_object = probe_read_object
        try:
            with self.assertRaises(_ReadProbe):
                complete_closure.validate_bundle(
                    Path("unused-bundle.json"),
                    artifact_root=Path("unused-artifacts"),
                    expected_commit=None,
                    expected_tree=None,
                    require_complete=False,
                    require_accepted=False,
                    trust_registry_path=None,
                    expected_trust_registry_sha256=None,
                )
        finally:
            complete_closure.read_object = original_read_object

        self.assertEqual(observed, [True])
        self.assertIsNone(_READ_SNAPSHOT.get())

    def test_acceptance_module_and_policy_module_share_one_entrypoint(self) -> None:
        self.assertIs(acceptance.validate_bundle, complete_closure.validate_bundle)


if __name__ == "__main__":
    unittest.main()
