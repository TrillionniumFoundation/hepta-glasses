#!/usr/bin/env python3
"""Print current tracked source identity and derived counts; never attest CI."""
import json
import subprocess
from collections import Counter
from pathlib import Path
try:
    from .validate_source_coverage import inspect_repository
except ImportError:
    from validate_source_coverage import inspect_repository


def snapshot(root: Path) -> dict:
    subprocess.run(["git", "diff", "--exit-code", "HEAD", "--"], cwd=root, check=True, stdout=subprocess.DEVNULL)
    identity = subprocess.check_output(["git", "rev-parse", "HEAD", "HEAD^{tree}"], cwd=root, text=True).splitlines()
    coverage = inspect_repository(root)
    rows = []
    for name in ("GAP_LEDGER.yaml", "G9_GAP_LEDGER.json", "G10_GAP_LEDGER.json", "REMEDIATION_GAP_LEDGER.json"):
        document = json.loads((root / "docs" / name).read_text())
        rows.extend(document["gaps"])
    ids = [row["id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate gap IDs across active ledgers")
    return {"schema_version": 1, "commit": identity[0], "tree": identity[1],
        "module_count": coverage["module_count"], "tracked_source_count": coverage["tracked_source_count"],
        "gap_count": len(rows), "gap_status_counts": dict(Counter(row["status"] for row in rows)),
        "open_gap_ids": [row["id"] for row in rows if row["status"] == "OPEN"],
        "ci_status": "not_observed", "independent_review": "not_observed", "release_authorized": False,
        "warning": "This local projection is not external evidence; query GitHub jobs, artifacts and reviews for this exact head."}


if __name__ == "__main__":
    print(json.dumps(snapshot(Path(__file__).resolve().parents[1]), indent=2, sort_keys=True))
