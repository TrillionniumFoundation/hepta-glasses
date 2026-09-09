#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import stat
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import PurePosixPath
from typing import Any

API = "https://api.github.com"
EXPECTED_JOBS = {
    "repository-contracts",
    "flutter",
    "android-native",
    "ios-native",
    "native-sanitizers",
    "secret-and-boundary-scan",
    "source-evidence",
}
EXPECTED_MEMBERS = {
    "source-evidence-summary.json",
    "source-gate-result.json",
    "source-history-scan.json",
    "source-native-sanitizer.json",
    "source-provenance.json",
    "source-release-bundle.json",
    "source-sbom.spdx.json",
}


class AuditFailure(RuntimeError):
    pass


def api_request(
    repository: str,
    token: str,
    path: str,
    *,
    method: str = "GET",
    body: Any | None = None,
    accept: str = "application/vnd.github+json",
) -> tuple[int, Any, bytes]:
    url = path if path.startswith("https://") else API + path
    payload = None if body is None else json.dumps(body, separators=(",", ":")).encode()
    request = urllib.request.Request(
        url,
        data=payload,
        method=method,
        headers={
            "Accept": accept,
            "Authorization": f"Bearer {token}",
            "User-Agent": "hepta-exact-head-source-audit/1",
            "X-GitHub-Api-Version": "2022-11-28",
            **({"Content-Type": "application/json"} if payload is not None else {}),
        },
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        return response.status, response.headers, response.read()


def get_json(repository: str, token: str, path: str) -> Any:
    _, _, payload = api_request(repository, token, path)
    return json.loads(payload)


def strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AuditFailure(f"duplicate JSON member: {key}")
        result[key] = value
    return result


def reject_constant(value: str) -> None:
    raise AuditFailure(f"non-finite JSON value: {value}")


def strict_json(raw: bytes) -> Any:
    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=strict_pairs,
            parse_constant=reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise AuditFailure(f"invalid strict JSON: {exc}") from exc


def branch_head(repository: str, token: str, branch: str) -> str:
    document = get_json(repository, token, f"/repos/{repository}/git/ref/heads/{branch}")
    value = document["object"]["sha"]
    if not isinstance(value, str) or len(value) != 40:
        raise AuditFailure(f"invalid branch head for {branch}: {value!r}")
    return value


def unresolved_threads(repository: str, token: str, pr: int) -> int:
    owner, name = repository.split("/", 1)
    query = """
    query($owner:String!,$name:String!,$number:Int!,$cursor:String){
      repository(owner:$owner,name:$name){
        pullRequest(number:$number){
          reviewThreads(first:100,after:$cursor){
            nodes{isResolved}
            pageInfo{hasNextPage endCursor}
          }
        }
      }
    }
    """
    cursor = None
    count = 0
    while True:
        _, _, payload = api_request(
            repository,
            token,
            "https://api.github.com/graphql",
            method="POST",
            body={
                "query": query,
                "variables": {
                    "owner": owner,
                    "name": name,
                    "number": pr,
                    "cursor": cursor,
                },
            },
        )
        document = json.loads(payload)
        if document.get("errors"):
            raise AuditFailure(f"GraphQL review-thread error: {document['errors']}")
        threads = document["data"]["repository"]["pullRequest"]["reviewThreads"]
        count += sum(1 for item in threads["nodes"] if not item["isResolved"])
        if not threads["pageInfo"]["hasNextPage"]:
            return count
        cursor = threads["pageInfo"]["endCursor"]


def wait_for_run(
    repository: str,
    token: str,
    *,
    branch: str,
    head: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    encoded = urllib.parse.quote(branch, safe="")
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if branch_head(repository, token, branch) != head:
            raise AuditFailure("candidate head moved during qualification wait")
        runs = get_json(
            repository,
            token,
            f"/repos/{repository}/actions/workflows/ci.yml/runs?branch={encoded}&per_page=50",
        )["workflow_runs"]
        matches = [
            item
            for item in runs
            if item.get("head_sha") == head and item.get("event") == "pull_request"
        ]
        if matches:
            run = max(matches, key=lambda item: (item["run_number"], item["run_attempt"]))
            if run["status"] == "completed":
                return run
        time.sleep(20)
    raise AuditFailure("timed out waiting for exact-head canonical workflow")


def audit(
    *,
    repository: str,
    token: str,
    pr_number: int,
    branch: str,
    expected_base: str,
    parent_branch: str,
    sentinel: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    pr = get_json(repository, token, f"/repos/{repository}/pulls/{pr_number}")
    if pr["state"] != "open" or pr["draft"] is not True:
        raise AuditFailure("pull request must remain open and Draft")
    if pr["head"]["ref"] != branch or pr["base"]["ref"] != expected_base:
        raise AuditFailure(
            f"pull request stack differs: head={pr['head']['ref']} base={pr['base']['ref']}"
        )

    head = branch_head(repository, token, branch)
    if pr["head"]["sha"] != head:
        raise AuditFailure("pull request head differs from branch head")
    parent = branch_head(repository, token, parent_branch)
    comparison = get_json(
        repository,
        token,
        f"/repos/{repository}/compare/{parent}...{head}",
    )
    if comparison["status"] not in {"ahead", "identical"}:
        raise AuditFailure(
            f"candidate is not descended from parent: {comparison['status']}"
        )
    if comparison["status"] != "ahead" or comparison["ahead_by"] < 1:
        raise AuditFailure("candidate must contain a non-empty child delta")

    sentinel_document = get_json(
        repository,
        token,
        f"/repos/{repository}/contents/{sentinel}?ref={head}",
    )
    if sentinel_document.get("type") != "file" or sentinel_document.get("encoding") != "base64":
        raise AuditFailure("stack sentinel is not a base64 file")
    sentinel_raw = base64.b64decode(
        sentinel_document["content"].replace("\r", "").replace("\n", ""),
        validate=True,
    )
    sentinel_text = sentinel_raw.decode("utf-8")
    if not sentinel_text.strip() or "No CI, Artifact, review" not in sentinel_text:
        raise AuditFailure("stack sentinel was not connector-finalized")

    run = wait_for_run(
        repository,
        token,
        branch=branch,
        head=head,
        timeout_seconds=timeout_seconds,
    )
    if run["conclusion"] != "success":
        raise AuditFailure(f"canonical run failed: {run['html_url']}")

    jobs = get_json(
        repository,
        token,
        f"/repos/{repository}/actions/runs/{run['id']}/jobs?per_page=100",
    )["jobs"]
    if len(jobs) != 7 or {job["name"] for job in jobs} != EXPECTED_JOBS:
        raise AuditFailure(f"canonical job set differs: {[job['name'] for job in jobs]}")
    for job in jobs:
        if job["status"] != "completed" or job["conclusion"] != "success":
            raise AuditFailure(f"job did not succeed: {job['name']}={job['conclusion']}")
        if not job.get("steps"):
            raise AuditFailure(f"job is empty: {job['name']}")
        for step in job["steps"]:
            if step["status"] != "completed" or step["conclusion"] not in {"success", "skipped"}:
                raise AuditFailure(f"step failed: {job['name']} / {step['name']}")

    artifacts = get_json(
        repository,
        token,
        f"/repos/{repository}/actions/runs/{run['id']}/artifacts?per_page=100",
    )["artifacts"]
    expected_name = f"hepta-source-evidence-{head}"
    matches = [item for item in artifacts if item["name"] == expected_name and not item["expired"]]
    if len(matches) != 1:
        raise AuditFailure(f"exact-head Artifact set differs: {[(item['name'], item['expired']) for item in artifacts]}")
    artifact = matches[0]
    _, _, archive = api_request(
        repository,
        token,
        f"/repos/{repository}/actions/artifacts/{artifact['id']}/zip",
    )
    zip_digest = hashlib.sha256(archive).hexdigest()
    server_digest = artifact.get("digest")
    if server_digest is not None and server_digest != f"sha256:{zip_digest}":
        raise AuditFailure("Artifact server digest differs from downloaded bytes")

    with zipfile.ZipFile(io.BytesIO(archive)) as package:
        infos = package.infolist()
        names = [info.filename for info in infos]
        if len(names) != 7 or len(set(names)) != 7 or set(names) != EXPECTED_MEMBERS:
            raise AuditFailure(f"Artifact inventory differs: {names}")
        if package.testzip() is not None:
            raise AuditFailure("Artifact CRC failed")
        raw: dict[str, bytes] = {}
        for info in infos:
            path = PurePosixPath(info.filename)
            mode = (info.external_attr >> 16) & 0xFFFF
            if (
                path.is_absolute()
                or ".." in path.parts
                or "\\" in info.filename
                or "\x00" in info.filename
                or info.is_dir()
                or (mode != 0 and not stat.S_ISREG(mode))
            ):
                raise AuditFailure(f"unsafe Artifact member: {info.filename}")
            raw[info.filename] = package.read(info)

    objects = {name: strict_json(value) for name, value in raw.items()}
    digests = {name: hashlib.sha256(value).hexdigest() for name, value in raw.items()}
    summary = objects["source-evidence-summary.json"]
    gate = objects["source-gate-result.json"]
    history = objects["source-history-scan.json"]
    native = objects["source-native-sanitizer.json"]
    provenance = objects["source-provenance.json"]
    release_document = objects["source-release-bundle.json"]
    release = release_document.get("source", release_document)
    sbom = objects["source-sbom.spdx.json"]
    tree = get_json(repository, token, f"/repos/{repository}/commits/{head}")["commit"]["tree"]["sha"]

    checks = {
        "summary_commit": summary.get("commit") == head,
        "summary_tree": summary.get("tree") == tree,
        "summary_native_digest": summary.get("native_sanitizer_digest") == digests["source-native-sanitizer.json"],
        "summary_provenance_digest": summary.get("provenance_digest") == digests["source-provenance.json"],
        "summary_sbom_digest": summary.get("sbom_digest") == digests["source-sbom.spdx.json"],
        "summary_counts": summary.get("package_count") == len(sbom.get("packages", [])) and summary.get("file_count") == len(sbom.get("files", [])),
        "gate_source": gate.get("mode") == "source",
        "gate_passed": gate.get("passed") is True,
        "gate_missing": gate.get("missing") == [],
        "gate_17": len(gate.get("checks", {})) == 17 and all(value is True for value in gate.get("checks", {}).values()),
        "history_head": history.get("head") == head,
        "history_clean": history.get("finding_count") == 0 and history.get("findings") == [] and history.get("unscanned_blob_count") == 0 and history.get("unscanned_blobs") == [] and history.get("unused_acknowledgement_count") == 0 and history.get("unused_acknowledgements") == [],
        "history_accounting": history.get("raw_finding_count") == history.get("acknowledged_finding_count") + history.get("finding_count"),
        "native_passed": native.get("passed") is True,
        "native_android": native.get("android_lc3", {}).get("passed") is True,
        "native_ios": native.get("ios_lc3", {}).get("passed") is True,
        "native_rnnoise": native.get("rnnoise", {}).get("passed") is True,
        "native_parity": native.get("lc3_cross_platform_parity") is True and native.get("android_lc3", {}).get("pcm_digest") == native.get("ios_lc3", {}).get("pcm_digest"),
        "native_sanitizers": native.get("sanitizers") == ["address", "undefined"],
        "provenance_identity": provenance.get("repository") == repository and provenance.get("commit") == head and provenance.get("tree") == tree,
        "provenance_crossdigests": provenance.get("history_scan_digest") == digests["source-history-scan.json"] and provenance.get("native_sanitizer_digest") == digests["source-native-sanitizer.json"] and provenance.get("sbom_digest") == digests["source-sbom.spdx.json"],
        "release_identity": release.get("commit") == head and release.get("tree") == tree,
        "release_ci": len(release.get("ci_checks", [])) == 6 and all(item.get("conclusion") == "success" for item in release.get("ci_checks", [])),
        "release_crossdigests": release.get("history_scan", {}).get("sha256") == digests["source-history-scan.json"] and release.get("native_sanitizer", {}).get("sha256") == digests["source-native-sanitizer.json"] and release.get("provenance", {}).get("sha256") == digests["source-provenance.json"] and release.get("sbom", {}).get("sha256") == digests["source-sbom.spdx.json"],
        "sbom_spdx": sbom.get("spdxVersion") == "SPDX-2.3" and sbom.get("dataLicense") == "CC0-1.0",
        "sbom_identity": sbom.get("name") == f"{repository}@{head}" and head in sbom.get("documentNamespace", ""),
        "sbom_sha256": all(any(checksum.get("algorithm") == "SHA256" and len(checksum.get("checksumValue", "")) == 64 for checksum in file.get("checksums", [])) for file in sbom.get("files", [])),
        "no_evidence_transfer": all("evidence_transfer" not in item for item in (summary, provenance, release)),
    }
    failed = sorted(name for name, value in checks.items() if not value)
    if failed:
        raise AuditFailure(f"Artifact checks failed: {failed}")
    open_threads = unresolved_threads(repository, token, pr_number)
    if open_threads:
        raise AuditFailure(f"unresolved review threads remain: {open_threads}")

    result = {
        "passed": True,
        "pr": pr_number,
        "base": expected_base,
        "parent_head": parent,
        "head": head,
        "tree": tree,
        "run_id": run["id"],
        "run_number": run["run_number"],
        "artifact_id": artifact["id"],
        "artifact_name": artifact["name"],
        "artifact_size": artifact["size_in_bytes"],
        "zip_sha256": zip_digest,
        "check_count": len(checks),
        "package_count": len(sbom.get("packages", [])),
        "file_count": len(sbom.get("files", [])),
        "unresolved_threads": open_threads,
    }
    comment = f"""## External exact-head source packet audit — PASSED / REVIEW REQUIRED

Bound only to base branch `{expected_base}` at parent `{parent}`, head `{head}`, tree `{tree}`, canonical run `{run['id']}` / #{run['run_number']}, and Artifact `{artifact['id']}` / `{artifact['name']}` with ZIP SHA-256 `{zip_digest}`.

The seven canonical jobs are non-empty and successful. The exact safe seven-member Artifact passes CRC, strict duplicate/non-finite JSON parsing, commit/tree binding, the 17/17 source gate, complete-history accounting, LC3/RNNoise parity and sanitizers, provenance/release cross-digests, SPDX 2.3 SBOM ({result['package_count']} packages / {result['file_count']} files), and no evidence transfer. There are zero unresolved review threads.

This operations audit is not an approval and does not authenticate provider, device, firmware, KMS/HSM, attestation, signing, store or release facts. A fresh eligible non-pusher review of this exact tuple remains required. Any source/base movement invalidates this packet.
"""
    api_request(
        repository,
        token,
        f"/repos/{repository}/issues/{pr_number}/comments",
        method="POST",
        body={"body": comment},
    )
    try:
        api_request(
            repository,
            token,
            f"/repos/{repository}/pulls/{pr_number}/requested_reviewers",
            method="POST",
            body={"reviewers": ["Franksudoman", "Tomasrgbsf"]},
        )
    except urllib.error.HTTPError as exc:
        if exc.code not in {409, 422}:
            raise
    print(json.dumps(result, sort_keys=True))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--expected-base", required=True)
    parser.add_argument("--parent-branch", required=True)
    parser.add_argument("--sentinel", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=1500)
    args = parser.parse_args()
    audit(
        repository=args.repository,
        token=args.token,
        pr_number=args.pr,
        branch=args.branch,
        expected_base=args.expected_base,
        parent_branch=args.parent_branch,
        sentinel=args.sentinel,
        timeout_seconds=args.timeout_seconds,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AuditFailure, AssertionError, KeyError, TypeError, ValueError) as exc:
        print(json.dumps({"passed": False, "error": str(exc)}, sort_keys=True))
        raise SystemExit(1)
