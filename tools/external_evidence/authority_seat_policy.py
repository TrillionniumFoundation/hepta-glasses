"""Global issuer-seat consistency for complete external-evidence closure."""

from __future__ import annotations

from types import ModuleType
from typing import Any, Mapping, Sequence


def install_global_authority_seat_policy(
    complete_closure: ModuleType,
    core: ModuleType,
) -> None:
    """Prevent one key or identity pair from impersonating different roles.

    The G10 base policy already requires distinct seats inside each gap. This
    installation adds the cross-gap invariant: one issuer key ID and one
    identity/organization pair may be reused only for the *same* authority
    class. A physical-device lab can therefore attest multiple physical gaps
    with one narrowly scoped key, while an omnipotent key cannot also act as a
    credential provider, cloud-security owner, store authority, or any other
    distinct role in the same complete package.
    """

    base_coverage = complete_closure._issuer_authority_coverage

    def issuer_authority_coverage(
        submissions: Sequence[Mapping[str, Any]],
        *,
        contract: Mapping[str, Any],
    ) -> tuple[dict[str, dict[str, list[str]]], dict[str, list[str]]]:
        coverage, missing = base_coverage(
            submissions,
            contract=contract,
        )

        class_by_key: dict[str, str] = {}
        class_by_identity: dict[tuple[str, str], str] = {}
        for index, submission in enumerate(submissions):
            label = f"validated_submissions[{index}]"
            authority_class = core.require_string(
                submission.get("authority_class"),
                label=f"{label}.authority_class",
                maximum=80,
            )
            key_id = core.require_string(
                submission.get("issuer_key_id"),
                label=f"{label}.issuer_key_id",
                maximum=500,
            )
            identity = core.require_string(
                submission.get("issuer_identity"),
                label=f"{label}.issuer_identity",
                maximum=300,
            )
            organization = core.require_string(
                submission.get("issuer_organization"),
                label=f"{label}.issuer_organization",
                maximum=300,
            )

            previous_key_class = class_by_key.setdefault(
                key_id,
                authority_class,
            )
            if previous_key_class != authority_class:
                core.fail(
                    f"issuer key {key_id} spans authority classes "
                    f"{previous_key_class} and {authority_class}; one pinned "
                    "key cannot occupy different authority roles"
                )

            identity_pair = (identity, organization)
            previous_identity_class = class_by_identity.setdefault(
                identity_pair,
                authority_class,
            )
            if previous_identity_class != authority_class:
                core.fail(
                    f"issuer identity {identity!r} from {organization!r} "
                    f"spans authority classes {previous_identity_class} and "
                    f"{authority_class}; one identity/organization pair "
                    "cannot occupy different authority roles"
                )

        return coverage, missing

    complete_closure._issuer_authority_coverage = issuer_authority_coverage
