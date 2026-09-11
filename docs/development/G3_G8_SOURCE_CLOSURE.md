# G3–G8 source closure package

This package supplies the repository-side implementations that were absent from the first foundation PR.

| Gate | Source implementation | Required external continuation |
|---|---|---|
| G3 | `services/control_plane/identity.py` | KMS/HSM, platform attestation, deployed account recovery and revoke drill |
| G4 | `services/control_plane/realtime.py` and physical trace evaluator | provider tenancy, physical Android/iOS audio traces, power and thermal report |
| G5 | `services/control_plane/capabilities.py` | real OAuth apps and authoritative external-system receipts |
| G6 | existing bounded Codex worker plus updated contracts | deployed worker identity, egress, secrets and compromise exercise |
| G7 | `services/skills/registry.py`, `services/skills/memory.py` | production signing roots and encrypted persistent storage |
| G8 | qualification, SBOM, provenance, release gate and governance tools | independent reviews, signing identities, pilot, drills and store approvals |

## Local checks

```bash
python3 tools/validate_repository.py
python3 -m unittest discover -s services -p 'test_*.py'
python3 -m unittest discover -s adapters -p 'test_*.py'
python3 -m compileall -q services adapters tools
flutter pub get
flutter analyze --no-fatal-infos --no-fatal-warnings
flutter test
```

## Exact-head source evidence

```bash
CI_REPOSITORY_CONTRACTS=success \
CI_FLUTTER=success \
CI_SECRET_SCAN=success \
python3 tools/build_source_evidence.py --output-dir build/evidence

python3 tools/evaluate_release_gate.py \
  --bundle build/evidence/source-release-bundle.json \
  --mode source
```

A source pass means the repository package is coherent. It is not a physical-device or public-release pass.
