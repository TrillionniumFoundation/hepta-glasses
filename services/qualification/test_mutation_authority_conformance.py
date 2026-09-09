from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.control_plane.mutation_authority import (
    MutationLeaseAuthority,
    MutationPrincipal,
)

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "contracts/conformance/mutation-authority-v1.json"


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )


class VectorIdentity:
    def __init__(self, principal: dict[str, object], credential: str) -> None:
        self.principal = principal
        self.credential = credential
        self.calls = 0

    def verify(
        self, *, bearer_token: str, audience: str, required_scope: str
    ) -> MutationPrincipal:
        self.calls += 1
        if bearer_token != self.credential:
            raise AssertionError("credential drifted from the test boundary")
        if audience != self.principal["audience"]:
            raise AssertionError("audience drifted from the conformance vector")
        scopes = tuple(str(item) for item in self.principal["scopes"])
        if required_scope not in scopes:
            raise AssertionError("required scope is absent")
        return MutationPrincipal(
            subject=str(self.principal["subject"]),
            device_id=str(self.principal["device_id"]),
            session_id=str(self.principal["session_id"]),
            audience=str(self.principal["audience"]),
            scopes=scopes,
            policy_hash=str(self.principal["policy_hash"]),
            user_present=bool(self.principal["user_present"]),
            biometric_verified=bool(self.principal["biometric_verified"]),
            expires_at=int(self.principal["expires_at_epoch_seconds"]),
        )


class MutationAuthorityConformanceTest(unittest.TestCase):
    def test_server_mints_the_mobile_conformance_vector(self) -> None:
        document = json.loads(CONTRACT.read_text(encoding="utf-8"))
        self.assertEqual(
            document["contract_id"],
            "hepta-mutation-authority-conformance-v1",
        )
        self.assertEqual(document["schema_version"], 1)
        request = document["request"]
        principal = document["principal"]

        argument_digest = hashlib.sha256(
            canonical_json(request["arguments"]).encode("utf-8")
        ).hexdigest()
        self.assertEqual(argument_digest, document["expected_argument_digest"])
        fingerprint_document = {
            "subject": principal["subject"],
            "device_id": principal["device_id"],
            "session_id": principal["session_id"],
            "task_id": request["task_id"],
            "action": request["action"],
            "risk_tier": request["risk_tier"],
            "argument_digest": argument_digest,
            "deadline_epoch_seconds": request["deadline_epoch_seconds"],
            "policy_hash": principal["policy_hash"],
        }
        fingerprint = hashlib.sha256(
            canonical_json(fingerprint_document).encode("utf-8")
        ).hexdigest()
        self.assertEqual(fingerprint, document["expected_fingerprint"])

        credential = "v" * 24
        identity = VectorIdentity(principal, credential)
        with tempfile.TemporaryDirectory() as directory:
            authority = MutationLeaseAuthority(
                str(Path(directory) / "authority.sqlite"),
                identity=identity,
                clock=lambda: document["now_epoch_seconds"],
            )
            try:
                body = canonical_json(request).encode("utf-8")
                with patch(
                    "services.control_plane.mutation_authority.secrets.token_urlsafe",
                    return_value=document["lease_token_component"],
                ):
                    response = authority.authorize(
                        authorization="Bearer " + credential,
                        body=body,
                    )
                    replay = authority.authorize(
                        authorization="Bearer " + credential,
                        body=body,
                    )

                self.assertEqual(response, document["expected_response"])
                self.assertEqual(replay, response)
                row = authority.db.execute(
                    "SELECT fingerprint,argument_digest FROM mutation_leases"
                ).fetchone()
                self.assertEqual(row["fingerprint"], document["expected_fingerprint"])
                self.assertEqual(
                    row["argument_digest"],
                    document["expected_argument_digest"],
                )
                self.assertEqual(
                    authority.db.execute(
                        "SELECT COUNT(*) FROM mutation_leases"
                    ).fetchone()[0],
                    1,
                )
                self.assertEqual(identity.calls, 2)
            finally:
                authority.close()


if __name__ == "__main__":
    unittest.main()
