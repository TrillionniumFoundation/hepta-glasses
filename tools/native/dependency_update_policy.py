#!/usr/bin/env python3
"""Fail-closed dependency admission and external CocoaPods update contract."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sys
import unicodedata
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

_OFFICIAL_REPOSITORY = "github/docs"
_OFFICIAL_PATH = "data/reusables/dependabot/supported-package-managers.md"
_MAX_RESPONSE_BYTES = 1024 * 1024

_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_BLOB_SHA = re.compile(r"^[0-9a-f]{40}$")
_SHA1 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COCOAPODS_VERSION = re.compile(r"^[0-9]+(?:\.[0-9]+){1,3}$")
_BASE64_WITH_LINE_BREAKS = re.compile(r"^[A-Za-z0-9+/=\r\n]*$")
_OFFICIAL_VALUE = re.compile(r"\|\s*`([a-z0-9][a-z0-9-]*)`\s*\|")
_CANONICAL_ECOSYSTEM = re.compile(
    r"(?m)^  - package-ecosystem: ([a-z0-9][a-z0-9-]*)$"
)

_POD_NAME = r"[A-Za-z0-9][A-Za-z0-9_.+\-/]*"
_POD_RECORD = re.compile(
    rf"^  - (?P<name>{_POD_NAME}) \((?P<version>[^()\r\n]+)\)(?P<children>:)?$"
)
_POD_CHILD = re.compile(
    rf"^    - (?P<name>{_POD_NAME})(?: \((?P<constraint>[^()\r\n]+)\))?$"
)
_DEPENDENCY_RECORD = re.compile(
    rf"^  - (?P<name>{_POD_NAME})(?P<metadata> \([^\r\n]+\))?$"
)
_EXTERNAL_SOURCE_NAME = re.compile(rf"^  (?P<name>{_POD_NAME}):$")
_EXTERNAL_SOURCE_FIELD = re.compile(
    r"^    (?P<key>:[a-z][a-z0-9_-]*): (?P<value>[^\r\n]+)$"
)
_SPEC_CHECKSUM = re.compile(
    rf"^  (?P<name>{_POD_NAME}): (?P<digest>[0-9a-f]{{40}})$"
)

# Reviewed raw-object identities. Any byte movement requires a fresh exact-head
# review. The hashes are calculated over the exact bytes read from Git, without
# newline normalization, decoding, re-encoding, or splitlines().
_APPROVED_DEPENDABOT_CONFIG_SHA256 = (
    "c50632e8373a28bceeb5fcd6716172a3cecf97e46f31ad85a49787c638f227a5"
)
_APPROVED_PODFILE_SHA256 = (
    "cf4f50875914e973aaed1f3627faebb458ce0550d3b59ab45a95e6410f882f80"
)
_APPROVED_PODFILE_LOCK_SHA256 = (
    "0c1b8e7654df3a9ba524d519a5547f22bb72ccf067b3f3f6552ab848d2fa975d"
)
_APPROVED_WORKFLOW_GIT_BLOB_SHA1 = (
    "7624aaf9cafa5bfef6b55f91d714bf50bb5c92ee"
)
_APPROVED_COCOAPODS_VERSION = "1.17.0"
_APPROVED_LOCK_PODS = {"Flutter": "1.0.0"}
_APPROVED_LOCK_DEPENDENCIES = {"Flutter": " (from `Flutter`)"}
_APPROVED_EXTERNAL_SOURCES = {"Flutter": {":path": "Flutter"}}
_APPROVED_SPEC_CHECKSUMS = {
    "Flutter": "71a624a5bc0c04062bf19101d501e466baf2fb47"
}
_APPROVED_PODFILE_LOCK_CHECKSUM = "9c46fd01abff66081b39f5fa5767b3f1d0b11d76"
_LOCK_SECTION_ORDER = (
    "PODS",
    "DEPENDENCIES",
    "EXTERNAL SOURCES",
    "SPEC CHECKSUMS",
    "PODFILE CHECKSUM",
    "COCOAPODS",
)

# Python str.splitlines() treats all of these as line boundaries. They are
# forbidden before parsing so Ruby/CocoaPods and Python can never disagree
# because a behavior-bearing byte was silently normalized to LF.
_NON_LF_LINE_BOUNDARIES = frozenset(
    {
        "\r",
        "\v",
        "\f",
        "\x1c",
        "\x1d",
        "\x1e",
        "\x85",
        "\u2028",
        "\u2029",
    }
)


class DependencyPolicyError(RuntimeError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(  # type: ignore[no-untyped-def]
        self, req, fp, code, msg, headers, newurl
    ):
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


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise DependencyPolicyError(
            f"cannot read {_display_path(path)}: {exc}"
        ) from exc


def _read(path: Path) -> str:
    raw = _read_bytes(path)
    try:
        return raw.decode("utf-8")
    except UnicodeError as exc:
        raise DependencyPolicyError(
            f"cannot read {_display_path(path)} as UTF-8: {exc}"
        ) from exc


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            _read(path),
            object_pairs_hook=_closed_object,
            parse_constant=_reject_constant,
        )
    except json.JSONDecodeError as exc:
        raise DependencyPolicyError(
            f"cannot parse {_display_path(path)}: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise DependencyPolicyError(
            f"{_display_path(path)} must be a JSON object"
        )
    return value


def _strict_utf8_lf_text(raw: bytes, label: str) -> str:
    """Decode one exact text object without normalizing any behavior byte."""
    if not raw:
        raise DependencyPolicyError(f"{label} must not be empty")
    if raw.startswith(b"\xef\xbb\xbf"):
        raise DependencyPolicyError(f"{label} must not contain a UTF-8 BOM")
    if not raw.endswith(b"\n"):
        raise DependencyPolicyError(
            f"{label} must end with exactly one ASCII LF"
        )
    if raw.endswith(b"\n\n"):
        raise DependencyPolicyError(
            f"{label} must end with exactly one ASCII LF, not a blank tail"
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DependencyPolicyError(
            f"{label} is not strict UTF-8: {exc}"
        ) from exc

    for index, char in enumerate(text):
        codepoint = ord(char)
        if char == "\n":
            continue
        category = unicodedata.category(char)
        if (
            char in _NON_LF_LINE_BOUNDARIES
            or codepoint < 0x20
            or 0x7F <= codepoint <= 0x9F
            or category in {"Cc", "Cf", "Cs", "Zl", "Zp"}
        ):
            raise DependencyPolicyError(
                f"{label} contains forbidden U+{codepoint:04X} "
                f"at character offset {index}"
            )

    return text


def _exact_text_object(
    value: bytes | str,
    label: str,
) -> tuple[bytes, str]:
    if isinstance(value, bytes):
        raw = value
    elif isinstance(value, str):
        raw = value.encode("utf-8")
    else:
        raise DependencyPolicyError(
            f"{label} must be bytes or text"
        )
    return raw, _strict_utf8_lf_text(raw, label)


def _raw_sha256(raw: bytes, label: str) -> str:
    digest = hashlib.sha256(raw).hexdigest()
    if not _SHA256.fullmatch(digest):
        raise DependencyPolicyError(f"{label} SHA-256 is malformed")
    return digest


def _string_list(value: Any, name: str) -> list[str]:
    if not isinstance(value, list) or not value or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise DependencyPolicyError(
            f"{name} must be a non-empty string array"
        )
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
        raise DependencyPolicyError(
            "dependency contract schema_version must be 2"
        )

    source = contract["official_source"]
    if not isinstance(source, dict) or set(source) != {
        "repository",
        "commit",
        "path",
        "retrieved_at",
    }:
        raise DependencyPolicyError(
            "official_source must use the closed source shape"
        )
    if source["repository"] != _OFFICIAL_REPOSITORY:
        raise DependencyPolicyError(
            "official source repository must be github/docs"
        )
    if source["path"] != _OFFICIAL_PATH:
        raise DependencyPolicyError(
            "official source path is not the GitHub package-manager table"
        )
    if not isinstance(source["commit"], str) or not _COMMIT.fullmatch(
        source["commit"]
    ):
        raise DependencyPolicyError(
            "official source commit must be a lowercase full Git SHA"
        )
    if not isinstance(source["retrieved_at"], str) or not re.fullmatch(
        r"20[0-9]{2}-[0-9]{2}-[0-9]{2}",
        source["retrieved_at"],
    ):
        raise DependencyPolicyError(
            "official source retrieval date must be YYYY-MM-DD"
        )

    configured = _string_list(
        contract["configured_ecosystems"], "configured_ecosystems"
    )
    unsupported = _string_list(
        contract["unsupported_repository_managers"],
        "unsupported_repository_managers",
    )
    minimum = contract["minimum_official_value_count"]
    if (
        isinstance(minimum, bool)
        or not isinstance(minimum, int)
        or minimum < 10
    ):
        raise DependencyPolicyError(
            "minimum_official_value_count must be an integer >= 10"
        )
    if set(configured) & set(unsupported):
        raise DependencyPolicyError(
            "configured and unsupported manager sets overlap"
        )
    return contract


def parse_official_values(document: str) -> set[str]:
    if "Package manager | YAML value" not in document:
        raise DependencyPolicyError(
            "official document is not the package-manager table"
        )
    values = set(_OFFICIAL_VALUE.findall(document))
    if not values:
        raise DependencyPolicyError(
            "official package-manager table yielded no YAML values"
        )
    return values


def _fetch_official_document(
    source: dict[str, Any],
) -> tuple[str, str, str]:
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
    request = Request(url, headers=headers, method="GET")
    try:
        with build_opener(_NoRedirect()).open(
            request, timeout=20
        ) as response:
            if response.geturl() != url:
                raise DependencyPolicyError(
                    "official-source request redirected unexpectedly"
                )
            if response.status != 200:
                raise DependencyPolicyError(
                    "official-source HTTP status was "
                    f"{response.status}, expected 200"
                )
            payload = response.read(_MAX_RESPONSE_BYTES + 1)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise DependencyPolicyError(
            f"official-source read failed closed: {exc}"
        ) from exc
    if len(payload) > _MAX_RESPONSE_BYTES:
        raise DependencyPolicyError(
            "official-source response exceeds one MiB"
        )

    try:
        metadata = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_closed_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DependencyPolicyError(
            f"official-source response is invalid JSON: {exc}"
        ) from exc
    if not isinstance(metadata, dict):
        raise DependencyPolicyError(
            "official-source response must be an object"
        )
    if metadata.get("type") != "file" or metadata.get("path") != path:
        raise DependencyPolicyError(
            "official-source response is not the pinned file"
        )
    blob_sha = metadata.get("sha")
    if not isinstance(blob_sha, str) or not _BLOB_SHA.fullmatch(blob_sha):
        raise DependencyPolicyError(
            "official-source blob SHA is missing or malformed"
        )
    encoded = metadata.get("content")
    if metadata.get("encoding") != "base64" or not isinstance(
        encoded, str
    ):
        raise DependencyPolicyError(
            "official-source content is not base64 encoded"
        )
    if not _BASE64_WITH_LINE_BREAKS.fullmatch(encoded):
        raise DependencyPolicyError(
            "official-source base64 contains non-alphabet bytes"
        )
    compact = encoded.replace("\r", "").replace("\n", "")
    try:
        raw = base64.b64decode(compact, validate=True)
        document = raw.decode("utf-8")
    except (ValueError, UnicodeError) as exc:
        raise DependencyPolicyError(
            f"official-source content decode failed: {exc}"
        ) from exc
    return document, blob_sha, url


def _configured_dependabot_values() -> list[str]:
    raw = _read_bytes(DEPENDABOT)
    digest = hashlib.sha256(raw).hexdigest()
    if digest != _APPROVED_DEPENDABOT_CONFIG_SHA256:
        raise DependencyPolicyError(
            "complete Dependabot object differs from the reviewed SHA-256: "
            f"observed={digest}, expected={_APPROVED_DEPENDABOT_CONFIG_SHA256}"
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeError as exc:
        raise DependencyPolicyError(
            f"Dependabot configuration is not UTF-8: {exc}"
        ) from exc
    values = _CANONICAL_ECOSYSTEM.findall(text)
    if values != ["github-actions", "pub", "gradle"]:
        raise DependencyPolicyError(
            "Dependabot ecosystem set/order differs from the reviewed object"
        )
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
            "Dependabot uses values absent from pinned GitHub docs: "
            f"{unsupported}"
        )
    falsely_supported = sorted(
        set(contract["unsupported_repository_managers"]) & official
    )
    if falsely_supported:
        raise DependencyPolicyError(
            "repository unsupported-manager classification conflicts with "
            f"pinned GitHub docs: {falsely_supported}"
        )
    if "swift" not in official:
        raise DependencyPolicyError(
            "pinned GitHub table unexpectedly lacks swift"
        )
    if PODFILE.is_file() and not (ROOT / "Package.swift").exists():
        if "swift" in configured:
            raise DependencyPolicyError(
                "swift cannot substitute for this repository's CocoaPods graph"
            )

    return {
        "schema_version": 2,
        "dependabot_config_sha256": _APPROVED_DEPENDABOT_CONFIG_SHA256,
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


def _pod_root(name: str) -> str:
    return name.split("/", 1)[0]


def _closed_lock_lines(
    lock_value: bytes | str,
) -> tuple[bytes, str, list[str]]:
    raw, text = _exact_text_object(lock_value, "Podfile.lock")
    # Deliberately parse only ASCII LF after the raw-object boundary check.
    lines = text[:-1].split("\n")
    if not lines or any(
        line.rstrip(" ") != line or "\t" in line for line in lines
    ):
        raise DependencyPolicyError(
            "Podfile.lock must be non-empty with no tabs or trailing spaces"
        )
    return raw, text, lines


def _split_lock_sections(
    lock_value: bytes | str,
) -> tuple[bytes, dict[str, list[str]]]:
    raw, _, lines = _closed_lock_lines(lock_value)
    sections: dict[str, list[str]] = {}
    current: str | None = None
    observed: list[str] = []

    for line in lines:
        if not line:
            continue
        if not line.startswith(" "):
            if line.endswith(":") and ": " not in line:
                name = line[:-1]
                if name not in _LOCK_SECTION_ORDER:
                    raise DependencyPolicyError(
                        f"unexpected Podfile.lock section: {name}"
                    )
                if name in sections:
                    raise DependencyPolicyError(
                        f"duplicate Podfile.lock section: {name}"
                    )
                if name in {"PODFILE CHECKSUM", "COCOAPODS"}:
                    raise DependencyPolicyError(
                        f"{name} must be a scalar line, not a block"
                    )
                current = name
                sections[name] = []
                observed.append(name)
                continue

            scalar_match = re.fullmatch(
                r"(PODFILE CHECKSUM|COCOAPODS): (.+)",
                line,
            )
            if scalar_match is None:
                raise DependencyPolicyError(
                    "malformed or unexpected Podfile.lock top-level line: "
                    f"{line!r}"
                )
            name, value = scalar_match.groups()
            if name in sections:
                raise DependencyPolicyError(
                    f"duplicate Podfile.lock section: {name}"
                )
            sections[name] = [value]
            observed.append(name)
            current = None
            continue

        if current is None:
            raise DependencyPolicyError(
                f"orphaned Podfile.lock indented line: {line!r}"
            )
        sections[current].append(line)

    if tuple(observed) != _LOCK_SECTION_ORDER:
        raise DependencyPolicyError(
            "Podfile.lock section order/set differs: "
            f"observed={observed}, expected={list(_LOCK_SECTION_ORDER)}"
        )
    if any(not sections[name] for name in _LOCK_SECTION_ORDER):
        raise DependencyPolicyError(
            "every Podfile.lock section must contain data"
        )
    return raw, sections


def _unique_add(
    values: dict[str, Any],
    name: str,
    value: Any,
    section: str,
) -> None:
    if name in values:
        raise DependencyPolicyError(
            f"duplicate {section} record for {name}"
        )
    values[name] = value


def parse_cocoapods_lock(
    lock_value: bytes | str,
) -> dict[str, Any]:
    raw, sections = _split_lock_sections(lock_value)

    pods: dict[str, str] = {}
    child_dependencies: dict[str, list[str]] = {}
    current_pod: str | None = None
    allows_children = False
    for line in sections["PODS"]:
        pod_match = _POD_RECORD.fullmatch(line)
        if pod_match:
            name = pod_match.group("name")
            _unique_add(
                pods, name, pod_match.group("version"), "PODS"
            )
            current_pod = name
            allows_children = pod_match.group("children") is not None
            child_dependencies[name] = []
            continue

        child_match = _POD_CHILD.fullmatch(line)
        if (
            child_match is None
            or current_pod is None
            or not allows_children
        ):
            raise DependencyPolicyError(
                f"malformed PODS record: {line!r}"
            )
        child_dependencies[current_pod].append(
            child_match.group("name")
        )

    dependencies: dict[str, str] = {}
    for line in sections["DEPENDENCIES"]:
        match = _DEPENDENCY_RECORD.fullmatch(line)
        if match is None:
            raise DependencyPolicyError(
                f"malformed DEPENDENCIES record: {line!r}"
            )
        _unique_add(
            dependencies,
            match.group("name"),
            match.group("metadata") or "",
            "DEPENDENCIES",
        )

    external_sources: dict[str, dict[str, str]] = {}
    current_source: str | None = None
    for line in sections["EXTERNAL SOURCES"]:
        name_match = _EXTERNAL_SOURCE_NAME.fullmatch(line)
        if name_match:
            current_source = name_match.group("name")
            _unique_add(
                external_sources,
                current_source,
                {},
                "EXTERNAL SOURCES",
            )
            continue
        field_match = _EXTERNAL_SOURCE_FIELD.fullmatch(line)
        if field_match is None or current_source is None:
            raise DependencyPolicyError(
                f"malformed EXTERNAL SOURCES record: {line!r}"
            )
        fields = external_sources[current_source]
        key = field_match.group("key")
        if key in fields:
            raise DependencyPolicyError(
                f"duplicate EXTERNAL SOURCES field {key} for {current_source}"
            )
        fields[key] = field_match.group("value")

    checksums: dict[str, str] = {}
    for line in sections["SPEC CHECKSUMS"]:
        match = _SPEC_CHECKSUM.fullmatch(line)
        if match is None:
            raise DependencyPolicyError(
                f"malformed SPEC CHECKSUMS record: {line!r}"
            )
        _unique_add(
            checksums,
            match.group("name"),
            match.group("digest"),
            "SPEC CHECKSUMS",
        )

    podfile_checksum = sections["PODFILE CHECKSUM"][0]
    if not _SHA1.fullmatch(podfile_checksum):
        raise DependencyPolicyError(
            "PODFILE CHECKSUM must be lowercase SHA-1 syntax"
        )
    cocoapods_version = sections["COCOAPODS"][0]
    if not _COCOAPODS_VERSION.fullmatch(cocoapods_version):
        raise DependencyPolicyError(
            "COCOAPODS must bind a dotted numeric version"
        )

    pod_roots = {_pod_root(name) for name in pods}
    dependency_roots = {_pod_root(name) for name in dependencies}
    source_roots = {_pod_root(name) for name in external_sources}
    checksum_roots = {_pod_root(name) for name in checksums}
    child_roots = {
        _pod_root(child)
        for children in child_dependencies.values()
        for child in children
    }

    if not dependency_roots <= pod_roots:
        raise DependencyPolicyError(
            "DEPENDENCIES references roots absent from PODS: "
            f"{sorted(dependency_roots - pod_roots)}"
        )
    if not child_roots <= pod_roots:
        raise DependencyPolicyError(
            "transitive PODS references roots absent from PODS: "
            f"{sorted(child_roots - pod_roots)}"
        )
    if source_roots - pod_roots:
        raise DependencyPolicyError(
            "EXTERNAL SOURCES references roots absent from PODS: "
            f"{sorted(source_roots - pod_roots)}"
        )
    if checksum_roots != pod_roots:
        raise DependencyPolicyError(
            "SPEC CHECKSUMS roots differ from PODS roots: "
            f"missing={sorted(pod_roots - checksum_roots)}, "
            f"extra={sorted(checksum_roots - pod_roots)}"
        )

    registry_roots = sorted(pod_roots - source_roots)
    return {
        "raw_sha256": _raw_sha256(raw, "Podfile.lock"),
        "pods": sorted(pods),
        "pod_versions": dict(sorted(pods.items())),
        "pod_roots": sorted(pod_roots),
        "dependencies": sorted(dependencies),
        "dependency_metadata": dict(sorted(dependencies.items())),
        "dependency_roots": sorted(dependency_roots),
        "child_dependencies": {
            name: list(children)
            for name, children in sorted(child_dependencies.items())
        },
        "external_sources": {
            name: dict(sorted(fields.items()))
            for name, fields in sorted(external_sources.items())
        },
        "spec_checksums": dict(sorted(checksums.items())),
        "podfile_checksum": podfile_checksum,
        "cocoapods_version": cocoapods_version,
        "registry_pod_roots": registry_roots,
        "external_registry_pods": len(registry_roots),
    }


def _podfile_digest(podfile: bytes | str) -> str:
    if isinstance(podfile, bytes):
        raw = podfile
    elif isinstance(podfile, str):
        raw = podfile.encode("utf-8")
    else:
        raise DependencyPolicyError("Podfile must be bytes or text")
    digest = _raw_sha256(raw, "Podfile")
    _strict_utf8_lf_text(raw, "Podfile")
    return digest


def _git_blob_sha1(payload: bytes) -> str:
    header = f"blob {len(payload)}\0".encode("ascii")
    return hashlib.sha1(header + payload).hexdigest()  # noqa: S324


def parse_canonical_ios_lock_step(workflow_text: str) -> dict[str, str]:
    """Locate one unconditional exact lock-install step in ios-native."""
    workflow_raw = workflow_text.encode("utf-8")
    workflow_text = _strict_utf8_lf_text(
        workflow_raw,
        "canonical workflow",
    )
    lines = workflow_text[:-1].split("\n")
    current_job: str | None = None
    matches: list[int] = []
    for index, line in enumerate(lines):
        job_match = re.fullmatch(r"  ([a-z0-9][a-z0-9-]*):", line)
        if job_match:
            current_job = job_match.group(1)
            continue
        if line != "      - name: Install locked CocoaPods dependencies":
            continue
        if current_job != "ios-native":
            raise DependencyPolicyError(
                "CocoaPods lock-install step is outside ios-native"
            )
        expected = [
            "      - name: Install locked CocoaPods dependencies",
            "        run: |",
            "          cd ios",
            "          pod install --deployment",
        ]
        if lines[index : index + len(expected)] != expected:
            raise DependencyPolicyError(
                "ios-native CocoaPods lock-install step differs from "
                "reviewed structure"
            )
        if index > 0 and lines[index - 1].lstrip().startswith("if:"):
            raise DependencyPolicyError(
                "ios-native CocoaPods lock-install step must be unconditional"
            )
        matches.append(index)

    if len(matches) != 1:
        raise DependencyPolicyError(
            "canonical workflow must contain exactly one reviewed "
            f"ios-native CocoaPods lock-install step, observed={len(matches)}"
        )
    return {
        "job": "ios-native",
        "step": "Install locked CocoaPods dependencies",
        "command": "cd ios && pod install --deployment",
    }


def verify_canonical_workflow() -> dict[str, str]:
    raw = _read_bytes(WORKFLOW)
    actual = _git_blob_sha1(raw)
    if actual != _APPROVED_WORKFLOW_GIT_BLOB_SHA1:
        raise DependencyPolicyError(
            "canonical workflow Git blob identity differs from the reviewed "
            f"object: observed={actual}, expected={_APPROVED_WORKFLOW_GIT_BLOB_SHA1}"
        )
    text = _strict_utf8_lf_text(raw, "canonical workflow")
    result = parse_canonical_ios_lock_step(text)
    result["git_blob_sha1"] = actual
    return result


def inspect_cocoapods() -> dict[str, Any]:
    podfile_raw = _read_bytes(PODFILE)
    lock_raw = _read_bytes(LOCKFILE)

    podfile_sha256 = _podfile_digest(podfile_raw)
    if podfile_sha256 != _APPROVED_PODFILE_SHA256:
        raise DependencyPolicyError(
            "Podfile raw bytes differ from the reviewed closed-world source; "
            "any Ruby, newline, encoding, helper, alias, variable, plugin "
            "installer, source, or target change requires an explicit policy update"
        )

    # Bind the complete raw lock object before decoding or semantic parsing.
    # This prevents parser differentials and makes every graph/encoding/newline
    # movement an explicit reviewed source change.
    lock_sha256 = _raw_sha256(lock_raw, "Podfile.lock")
    if lock_sha256 != _APPROVED_PODFILE_LOCK_SHA256:
        raise DependencyPolicyError(
            "Podfile.lock raw bytes differ from the reviewed closed-world object: "
            f"observed={lock_sha256}, expected={_APPROVED_PODFILE_LOCK_SHA256}"
        )
    _strict_utf8_lf_text(lock_raw, "Podfile.lock")

    graph = parse_cocoapods_lock(lock_raw)
    if graph["pod_versions"] != _APPROVED_LOCK_PODS:
        raise DependencyPolicyError(
            "PODS inventory/version differs from the reviewed "
            f"local-Flutter-only graph: {graph['pod_versions']}"
        )
    if graph["dependency_metadata"] != _APPROVED_LOCK_DEPENDENCIES:
        raise DependencyPolicyError(
            "DEPENDENCIES inventory/origin differs from the reviewed graph: "
            f"{graph['dependency_metadata']}"
        )
    if graph["child_dependencies"] != {"Flutter": []}:
        raise DependencyPolicyError(
            "unexpected transitive Pod dependencies: "
            f"{graph['child_dependencies']}"
        )
    if graph["external_sources"] != _APPROVED_EXTERNAL_SOURCES:
        raise DependencyPolicyError(
            "EXTERNAL SOURCES differs from the reviewed local Flutter path: "
            f"{graph['external_sources']}"
        )
    if graph["spec_checksums"] != _APPROVED_SPEC_CHECKSUMS:
        raise DependencyPolicyError(
            "SPEC CHECKSUMS differs from the reviewed graph: "
            f"{graph['spec_checksums']}"
        )
    if graph["podfile_checksum"] != _APPROVED_PODFILE_LOCK_CHECKSUM:
        raise DependencyPolicyError(
            "PODFILE CHECKSUM differs from the reviewed Podfile binding"
        )
    if graph["cocoapods_version"] != _APPROVED_COCOAPODS_VERSION:
        raise DependencyPolicyError(
            "COCOAPODS generator differs from the reviewed version: "
            f"observed={graph['cocoapods_version']}, "
            f"expected={_APPROVED_COCOAPODS_VERSION}"
        )
    if graph["external_registry_pods"] != 0:
        raise DependencyPolicyError(
            "registry-hosted Pods are prohibited until a reviewed updater and "
            f"trust policy exist: {graph['registry_pod_roots']}"
        )

    workflow = verify_canonical_workflow()
    return {
        "schema_version": 4,
        "mode": "closed-world-local-flutter-pod-only",
        "repository_executes_update": False,
        "podfile_sha256": podfile_sha256,
        "podfile_lock_sha256": lock_sha256,
        "lock_pods": graph["pods"],
        "lock_dependencies": graph["dependencies"],
        "lock_spec_checksums": sorted(graph["spec_checksums"]),
        "external_registry_pods": graph["external_registry_pods"],
        "registry_pod_roots": graph["registry_pod_roots"],
        "external_sources": sorted(graph["external_sources"]),
        "cocoapods_version": graph["cocoapods_version"],
        "approved_cocoapods_version": _APPROVED_COCOAPODS_VERSION,
        "ci_lock_enforcement": workflow,
        "auto_commit": False,
        "auto_push": False,
        "auto_merge": False,
    }


def emit_cocoapods_update_contract() -> dict[str, Any]:
    current = inspect_cocoapods()
    return {
        "schema_version": 1,
        "operation": "external-hermetic-cocoapods-lock-refresh",
        "repository_executes_generator": False,
        "repository_executes_flutter": False,
        "repository_executes_git": False,
        "current_input_bindings": {
            "podfile_sha256": current["podfile_sha256"],
            "podfile_lock_sha256": current["podfile_lock_sha256"],
            "canonical_workflow_git_blob_sha1": current[
                "ci_lock_enforcement"
            ]["git_blob_sha1"],
            "reviewed_cocoapods_version": _APPROVED_COCOAPODS_VERSION,
        },
        "allowed_repository_changes": ["ios/Podfile.lock"],
        "required_external_evidence": [
            "immutable_environment_digest",
            "ruby_interpreter_sha256",
            "cocoapods_gem_set_digest",
            "flutter_sdk_digest",
            "network_dependency_provenance",
            "generated_lock_sha256",
            "invocation_transcript_digest",
        ],
        "admission_requirements": [
            "review the complete lockfile diff",
            "update closed-world policy constants and hostile tests when the graph moves",
            "run all seven canonical jobs on one unchanged head",
            "download and content-verify the exact-head Artifact twice",
            "obtain an eligible non-pusher approval with all conversations resolved",
            "repeat signing, provider, and physical-device qualification when affected",
        ],
        "auto_commit": False,
        "auto_push": False,
        "auto_merge": False,
        "passed": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--verify-dependabot-official",
        action="store_true",
        help=(
            "read the pinned github/docs table and reject unsupported "
            "YAML values"
        ),
    )
    mode.add_argument(
        "--check-cocoapods",
        action="store_true",
        help="inspect the committed Pod graph without network access",
    )
    mode.add_argument(
        "--emit-cocoapods-update-contract",
        action="store_true",
        help=(
            "emit the non-executing external hermetic refresh requirements"
        ),
    )
    args = parser.parse_args(argv)

    try:
        if args.verify_dependabot_official:
            result = verify_dependabot_official()
        elif args.emit_cocoapods_update_contract:
            result = emit_cocoapods_update_contract()
        else:
            result = inspect_cocoapods()
    except DependencyPolicyError as exc:
        print(f"dependency-update-policy: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())