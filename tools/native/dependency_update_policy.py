#!/usr/bin/env python3
"""Fail-closed policy checks for dependency updates and CocoaPods locks."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[2]
DEPENDABOT = ROOT / ".github/dependabot.yml"
CONTRACT = ROOT / "contracts/dependabot-supported-ecosystems-v1.json"
PODFILE = ROOT / "ios/Podfile"
LOCKFILE = ROOT / "ios/Podfile.lock"
WORKFLOW = ROOT / ".github/workflows/ci.yml"
APPROVAL_ENV = "HEPTA_COCOAPODS_UPDATE_APPROVED"

_OFFICIAL_REPOSITORY = "github/docs"
_OFFICIAL_PATH = "data/reusables/dependabot/supported-package-managers.md"
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_BLOB_SHA = re.compile(r"^[0-9a-f]{40}$")
_POD_DECLARATION = re.compile(r"""^\s*pod\s+['\"]([^'\"]+)['\"]""")
_COCOAPODS_VERSION = re.compile(r"(?m)^COCOAPODS:\s+([0-9]+(?:\.[0-9]+){1,3})\s*$")
_ECOSYSTEM = re.compile(r"(?m)^  - package-ecosystem: ([a-z0-9][a-z0-9-]*)$")
_OFFICIAL_VALUE = re.compile(r"\|\s*`([a-z0-9][a-z0-9-]*)`\s*\|")
_BASE64_WITH_LINE_BREAKS = re.compile(r"^[A-Za-z0-9+/=\r\n]*$")
_MAX_RESPONSE_BYTES = 1024 * 1024


class DependencyPolicyError(RuntimeError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


def _reject_constant(value: str) -> None:
    raise DependencyPolicyError(f"non-finite JSON value is forbidden: {value}")


def _closed_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DependencyPolicyError(f"duplicate JSON member: {key}")
        result[key] = value
    return result


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_closed_object,
            parse_constant=_reject_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DependencyPolicyError(f"cannot parse {path.relative_to(ROOT)}: {exc}") from exc
    if not isinstance(value, dict):
        raise DependencyPolicyError(f"{path.relative_to(ROOT)} must be a JSON object")
    return value


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DependencyPolicyError(f"cannot read {path.relative_to(ROOT)}: {exc}") from exc


def _string_list(value: Any, name: str) -> list[str]:
    if not isinstance(value, list) or not value or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise DependencyPolicyError(f"{name} must be a non-empty string array")
    if value != sorted(set(value)):
        raise DependencyPolicyError(f"{name} must be unique and sorted")
    return list(value)


def load_contract() -> dict[str, Any]:
    contract = _load_json(CONTRACT)
    expected = {
        "schema_version",
        "official_source",
        "configured_ecosystems",
        "unsupported_repository_managers",
        "minimum_official_value_count",
    }
    if set(contract) != expected:
        raise DependencyPolicyError(
            f"dependency contract fields differ: {sorted(set(contract) ^ expected)}"
        )
    if contract["schema_version"] != 2:
        raise DependencyPolicyError("dependency contract schema_version must be 2")

    source = contract["official_source"]
    if not isinstance(source, dict) or set(source) != {
        "repository",
        "commit",
        "path",
        "retrieved_at",
    }:
        raise DependencyPolicyError("official_source must use the closed source shape")
    if source["repository"] != _OFFICIAL_REPOSITORY:
        raise DependencyPolicyError("official source repository must be github/docs")
    if source["path"] != _OFFICIAL_PATH:
        raise DependencyPolicyError("official source path is not the GitHub package-manager table")
    if not isinstance(source["commit"], str) or not _COMMIT.fullmatch(source["commit"]):
        raise DependencyPolicyError("official source commit must be a lowercase full Git SHA")
    if not isinstance(source["retrieved_at"], str) or not re.fullmatch(
        r"20[0-9]{2}-[0-9]{2}-[0-9]{2}", source["retrieved_at"]
    ):
        raise DependencyPolicyError("official source retrieval date must be YYYY-MM-DD")

    configured = _string_list(contract["configured_ecosystems"], "configured_ecosystems")
    unsupported = _string_list(
        contract["unsupported_repository_managers"],
        "unsupported_repository_managers",
    )
    minimum = contract["minimum_official_value_count"]
    if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 10:
        raise DependencyPolicyError("minimum_official_value_count must be an integer >= 10")
    if set(configured) & set(unsupported):
        raise DependencyPolicyError("configured and unsupported manager sets overlap")
    return contract


def parse_official_values(document: str) -> set[str]:
    if "Package manager | YAML value" not in document:
        raise DependencyPolicyError("official document is not the package-manager table")
    values = set(_OFFICIAL_VALUE.findall(document))
    if not values:
        raise DependencyPolicyError("official package-manager table yielded no YAML values")
    return values


def _fetch_official_document(source: dict[str, Any]) -> tuple[str, str, str]:
    repository = source["repository"]
    commit = source["commit"]
    path = source["path"]
    url = (
        f"https://api.github.com/repos/{repository}/contents/"
        f"{quote(path, safe='/')}?ref={commit}"
    )
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "hepta-glasses-dependency-policy/1",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        if "\n" in token or "\r" in token:
            raise DependencyPolicyError("GITHUB_TOKEN contains a forbidden newline")
        headers["Authorization"] = f"Bearer {token}"

    request = Request(url, headers=headers, method="GET")
    try:
        with build_opener(_NoRedirect()).open(request, timeout=20) as response:
            if response.geturl() != url:
                raise DependencyPolicyError("official-source request redirected unexpectedly")
            if response.status != 200:
                raise DependencyPolicyError(
                    f"official-source HTTP status was {response.status}, expected 200"
                )
            payload = response.read(_MAX_RESPONSE_BYTES + 1)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise DependencyPolicyError(f"official-source read failed closed: {exc}") from exc
    if len(payload) > _MAX_RESPONSE_BYTES:
        raise DependencyPolicyError("official-source response exceeds one MiB")

    try:
        metadata = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_closed_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DependencyPolicyError(f"official-source response is invalid JSON: {exc}") from exc
    if not isinstance(metadata, dict):
        raise DependencyPolicyError("official-source response must be an object")
    if metadata.get("type") != "file" or metadata.get("path") != path:
        raise DependencyPolicyError("official-source response is not the pinned file")
    blob_sha = metadata.get("sha")
    if not isinstance(blob_sha, str) or not _BLOB_SHA.fullmatch(blob_sha):
        raise DependencyPolicyError("official-source blob SHA is missing or malformed")
    encoded = metadata.get("content")
    if metadata.get("encoding") != "base64" or not isinstance(encoded, str):
        raise DependencyPolicyError("official-source content is not base64 encoded")
    if not _BASE64_WITH_LINE_BREAKS.fullmatch(encoded):
        raise DependencyPolicyError("official-source base64 contains non-alphabet bytes")
    compact = encoded.replace("\r", "").replace("\n", "")
    try:
        raw = base64.b64decode(compact, validate=True)
        document = raw.decode("utf-8")
    except (ValueError, UnicodeError) as exc:
        raise DependencyPolicyError(f"official-source content decode failed: {exc}") from exc
    return document, blob_sha, url


def _configured_dependabot_values() -> list[str]:
    values = _ECOSYSTEM.findall(_read(DEPENDABOT))
    if not values or len(values) != len(set(values)):
        raise DependencyPolicyError("Dependabot ecosystems must be present and unique")
    return sorted(values)


def verify_dependabot_official() -> dict[str, Any]:
    contract = load_contract()
    source = contract["official_source"]
    document, blob_sha, url = _fetch_official_document(source)
    official = parse_official_values(document)
    if len(official) < contract["minimum_official_value_count"]:
        raise DependencyPolicyError(
            f"official table yielded only {len(official)} values"
        )

    configured = _configured_dependabot_values()
    expected = contract["configured_ecosystems"]
    if configured != expected:
        raise DependencyPolicyError(
            f"Dependabot ecosystems {configured} differ from contract {expected}"
        )
    unsupported = sorted(set(configured) - official)
    if unsupported:
        raise DependencyPolicyError(
            f"Dependabot uses values absent from pinned GitHub docs: {unsupported}"
        )
    falsely_supported = sorted(
        set(contract["unsupported_repository_managers"]) & official
    )
    if falsely_supported:
        raise DependencyPolicyError(
            "repository unsupported-manager classification conflicts with pinned "
            f"GitHub docs: {falsely_supported}"
        )
    if "swift" not in official:
        raise DependencyPolicyError("pinned GitHub table unexpectedly lacks swift")
    if (ROOT / "ios/Podfile").is_file() and not (ROOT / "Package.swift").exists():
        if "swift" in configured:
            raise DependencyPolicyError(
                "swift cannot substitute for this repository's CocoaPods graph"
            )

    return {
        "schema_version": 1,
        "official_repository": source["repository"],
        "official_commit": source["commit"],
        "official_path": source["path"],
        "official_blob_sha": blob_sha,
        "official_value_count": len(official),
        "configured_ecosystems": configured,
        "unsupported_repository_managers": contract[
            "unsupported_repository_managers"
        ],
        "request_url": url,
        "passed": True,
    }


def _external_source_names(lock_text: str) -> list[str]:
    names: list[str] = []
    in_section = False
    for line in lock_text.splitlines():
        if line == "EXTERNAL SOURCES:":
            in_section = True
            continue
        if in_section and line and not line.startswith(" "):
            break
        if in_section:
            match = re.match(r"^  ([^:]+):\s*$", line)
            if match:
                names.append(match.group(1))
    return names


def inspect_cocoapods() -> dict[str, Any]:
    podfile = _read(PODFILE)
    lock = _read(LOCKFILE)
    workflow = _read(WORKFLOW)

    declarations = [
        match.group(1)
        for line in podfile.splitlines()
        if not line.lstrip().startswith("#")
        for match in [_POD_DECLARATION.match(line)]
        if match
    ]
    sources = _external_source_names(lock)
    version = _COCOAPODS_VERSION.search(lock)

    if declarations:
        raise DependencyPolicyError(
            "registry-hosted Pod declarations require a reviewed automation and "
            f"trust-policy extension before use: {sorted(declarations)}"
        )
    if sources != ["Flutter"] or ":path: Flutter" not in lock:
        raise DependencyPolicyError(
            "Podfile.lock must contain only the local Flutter source until an "
            f"external-Pod policy is accepted; observed sources={sources}"
        )
    if version is None:
        raise DependencyPolicyError("Podfile.lock does not bind a CocoaPods version")
    if "pod install --deployment" not in workflow:
        raise DependencyPolicyError(
            "canonical iOS qualification no longer enforces Podfile.lock"
        )

    return {
        "schema_version": 1,
        "mode": "local-flutter-pod-only",
        "external_registry_pods": 0,
        "external_sources": sources,
        "cocoapods_version": version.group(1),
        "ci_lock_enforcement": "pod install --deployment",
        "auto_commit": False,
        "auto_push": False,
        "auto_merge": False,
    }


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )


def _require_refresh_boundary() -> None:
    if os.environ.get(APPROVAL_ENV) != "1":
        raise DependencyPolicyError(
            f"--refresh-cocoapods requires {APPROVAL_ENV}=1 from an authorized operator"
        )
    for executable in ("flutter", "pod", "git"):
        if shutil.which(executable) is None:
            raise DependencyPolicyError(f"required executable is unavailable: {executable}")

    branch = _git("branch", "--show-current").stdout.strip()
    if not branch or branch == "main":
        raise DependencyPolicyError(
            "lock refresh must run on a named non-main review branch"
        )
    if _git("status", "--porcelain", "--untracked-files=all").stdout:
        raise DependencyPolicyError(
            "lock refresh requires a clean worktree so change custody is unambiguous"
        )


def refresh_cocoapods() -> dict[str, Any]:
    _require_refresh_boundary()
    subprocess.run(["flutter", "pub", "get"], cwd=ROOT, check=True)
    subprocess.run(
        ["pod", "update"],
        cwd=ROOT / "ios",
        check=True,
        env={**os.environ, "COCOAPODS_DISABLE_STATS": "true"},
    )

    changed: list[str] = []
    for line in _git("status", "--porcelain", "--untracked-files=all").stdout.splitlines():
        if len(line) < 4:
            raise DependencyPolicyError(f"cannot parse git status entry: {line!r}")
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        changed.append(path)
    changed = sorted(set(changed))
    if any(path != "ios/Podfile.lock" for path in changed):
        raise DependencyPolicyError(
            "refresh changed files outside ios/Podfile.lock; inspect without "
            f"committing or pushing: {changed}"
        )
    result = inspect_cocoapods()
    result["changed_files"] = changed
    result["operator_next_step"] = (
        "review the lockfile diff and open an ordinary exact-head pull request"
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--verify-dependabot-official",
        action="store_true",
        help="read the pinned github/docs table and reject unsupported YAML values",
    )
    mode.add_argument(
        "--check-cocoapods",
        action="store_true",
        help="inspect the committed Pod graph without network access",
    )
    mode.add_argument(
        "--refresh-cocoapods",
        action="store_true",
        help="refresh Podfile.lock on a clean authorized review branch",
    )
    args = parser.parse_args(argv)

    try:
        if args.verify_dependabot_official:
            result = verify_dependabot_official()
        elif args.refresh_cocoapods:
            result = refresh_cocoapods()
        else:
            result = inspect_cocoapods()
    except (DependencyPolicyError, subprocess.CalledProcessError) as exc:
        print(f"dependency-update-policy: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
