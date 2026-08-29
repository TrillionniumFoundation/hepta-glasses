"""Dependency-free SPDX-style source manifest and provenance generator."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable


EXCLUDED_PARTS = frozenset({".git", ".dart_tool", "build", "Pods"})
TEXT_EXTENSIONS = frozenset(
    {
        ".c",
        ".cc",
        ".cpp",
        ".dart",
        ".h",
        ".json",
        ".kt",
        ".m",
        ".md",
        ".py",
        ".sh",
        ".swift",
        ".toml",
        ".yaml",
        ".yml",
    }
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in EXCLUDED_PARTS for part in path.relative_to(root).parts):
            continue
        if path.suffix.lower() in TEXT_EXTENSIONS or path.name in {
            "LICENSE",
            "pubspec.lock",
            "pubspec.yaml",
        }:
            yield path


def parse_pubspec_lock(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    packages: list[dict[str, str]] = []
    current: str | None = None
    indent_re = re.compile(r"^  ([A-Za-z0-9_.-]+):\s*$")
    version_re = re.compile(r'^    version:\s+"?([^"\s]+)"?\s*$')
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = indent_re.match(line)
        if match:
            current = match.group(1)
            continue
        version = version_re.match(line)
        if current and version:
            packages.append({"name": current, "version": version.group(1)})
            current = None
    return packages


def build_sbom(root: Path, *, document_name: str, namespace: str) -> dict[str, Any]:
    root = root.resolve()
    files = [
        {
            "SPDXID": f"SPDXRef-File-{index}",
            "checksums": [
                {"algorithm": "SHA256", "checksumValue": sha256_file(path)}
            ],
            "fileName": str(path.relative_to(root)),
        }
        for index, path in enumerate(source_files(root), start=1)
    ]
    packages = [
        {
            "SPDXID": f"SPDXRef-Package-{index}",
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": False,
            "name": package["name"],
            "versionInfo": package["version"],
        }
        for index, package in enumerate(
            parse_pubspec_lock(root / "pubspec.lock"), start=1
        )
    ]
    return {
        "SPDXID": "SPDXRef-DOCUMENT",
        "creationInfo": {"creators": ["Tool: hepta-source-sbom-1"]},
        "dataLicense": "CC0-1.0",
        "documentNamespace": namespace,
        "files": files,
        "name": document_name,
        "packages": packages,
        "spdxVersion": "SPDX-2.3",
    }


def canonical_digest(document: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            document,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
