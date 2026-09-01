# Authority-owned evidence staging

This directory is a staging boundary for evidence that can close G9 authority-owned gaps. A file in this directory is not automatically trusted and is not automatically part of a release.

## Required layout

```text
evidence/external/
  <candidate-commit>/
    bundle.json
    artifacts/
      <gap-id>/...
    signatures/
      <artifact-id>.sig
    validation-result.json
```

`bundle.json` must use `hepta-external-evidence-envelope-v1`. Artifact URIs use `artifact://` and are resolved relative to the selected `artifacts` root. Network URLs are not dereferenced by the validator; externally hosted records must be exported into the custody package with a stable digest and, where applicable, a detached signature or provider receipt.

## Privacy and secret boundary

Never commit or upload:

- raw provider credentials, OAuth refresh tokens, KMS/HSM private material, application signing keys, or recovery secrets;
- raw microphone audio or sensitive transcripts;
- unredacted provider dashboards, customer data, notification bodies, precise location histories, or personal calendars;
- security reports containing live exploitation secrets that have not been separately access-controlled.

Use opaque KIDs, tenant IDs, receipt IDs, revocation timestamps, hashes, redacted logs, signed summaries, and independently verifiable attestations.

## Artifact rules

Every artifact must declare a unique ID, media type, issue time, optional expiry, SHA-256 digest, synthetic flag, and issuer key ID. Physical G1 and speech evidence must set `synthetic=false`; simulator and digital-twin results are rejected for HG-0010 and HG-0018.

Evidence copied from an external system must preserve the issuer's authoritative identity and timestamp. A screenshot is supplemental only unless its issuer, subject, candidate identity, timestamp, and integrity can be independently verified.

## Validation

```bash
python3 tools/validate_external_evidence.py \
  --bundle evidence/external/<commit>/bundle.json \
  --artifact-root evidence/external/<commit>/artifacts \
  --expected-commit <40-hex-source-commit> \
  --expected-tree <40-hex-source-tree> \
  --require-complete \
  --require-accepted \
  --output evidence/external/<commit>/validation-result.json
```

A successful result means the package meets deterministic admission requirements. It does not prove the issuer's real-world statements by itself. The independent accepting reviewer remains responsible for verifying signatures, provider/device authority, test custody, and scope.

## Ledger update rule

The Gap Ledger is changed only in a separate reviewed commit after:

1. the complete bundle passes;
2. the acceptance state is `accepted`;
3. required independent reviewers are present and are not evidence issuers;
4. the live candidate still matches the envelope;
5. no artifact is expired or revoked;
6. product release gate evaluation succeeds where E7 is claimed.

Any later source, binary, firmware, provider, OAuth registration, repository-setting, or review-state change reopens the affected row.