"""Deterministic multi-ecosystem SPDX 2.3 source manifest generation."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import quote

EXCLUDED_PARTS = frozenset(
    {".git", ".dart_tool", ".gradle", ".swiftpm", "build", "Pods"}
)
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
            "Podfile.lock",
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
            name = current
            value = version.group(1)
            packages.append(
                {
                    "ecosystem": "dart/pub",
                    "name": name,
                    "version": value,
                    "purl": f"pkg:pub/{quote(name)}@{quote(value)}",
                    "license": "NOASSERTION",
                    "supplier": "NOASSERTION",
                }
            )
            current = None
    return packages


def parse_gradle_dependencies(root: Path) -> list[dict[str, str]]:
    coordinates: set[tuple[str, str, str]] = set()
    coordinate_re = re.compile(
        r"['\"]([A-Za-z0-9_.-]+):([A-Za-z0-9_.-]+):([^'\"\s]+)['\"]"
    )
    plugin_re = re.compile(
        r"id\s+['\"]([^'\"]+)['\"]\s+version\s+['\"]([^'\"]+)['\"]"
    )
    for relative in (
        "android/app/build.gradle",
        "android/build.gradle",
        "android/settings.gradle",
    ):
        path = root / relative
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for group, name, version in coordinate_re.findall(text):
            coordinates.add((group, name, version))
        for plugin, version in plugin_re.findall(text):
            coordinates.add(("gradle.plugin", plugin, version))

    wrapper = root / "android/gradle/wrapper/gradle-wrapper.properties"
    if wrapper.is_file():
        match = re.search(
            r"gradle-([0-9][A-Za-z0-9_.-]*)-(?:all|bin)\.zip",
            wrapper.read_text(encoding="utf-8", errors="replace"),
        )
        if match:
            coordinates.add(("org.gradle", "gradle", match.group(1)))

    return [
        {
            "ecosystem": "android/gradle",
            "name": f"{group}:{name}",
            "version": version,
            "purl": f"pkg:maven/{quote(group)}/{quote(name)}@{quote(version)}",
            "license": "NOASSERTION",
            "supplier": "NOASSERTION",
        }
        for group, name, version in sorted(coordinates)
    ]


def parse_podfile_lock(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    packages: dict[str, str] = {}
    in_pods = False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line == "PODS:":
            in_pods = True
            continue
        if in_pods and line and not line.startswith(" "):
            in_pods = False
        if in_pods:
            match = re.match(r"^  - ([^ (]+) \(([^)]+)\)", line)
            if match:
                name = match.group(1).split("/")[0]
                packages.setdefault(name, match.group(2))
        tool = re.match(r"^COCOAPODS:\s+(.+)$", line)
        if tool:
            packages.setdefault("CocoaPods", tool.group(1).strip())
    return [
        {
            "ecosystem": "ios/cocoapods",
            "name": name,
            "version": version,
            "purl": f"pkg:cocoapods/{quote(name)}@{quote(version)}",
            "license": "NOASSERTION",
            "supplier": "NOASSERTION",
        }
        for name, version in sorted(packages.items())
    ]


def parse_native_inventory(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema_version") != 1:
        raise ValueError("unsupported native component inventory")
    components = document.get("components")
    if not isinstance(components, list):
        raise ValueError("native component inventory has no components")
    parsed: list[dict[str, Any]] = []
    for component in components:
        if not isinstance(component, Mapping):
            raise ValueError("native component must be an object")
        source_paths = component.get("source_paths")
        if not isinstance(source_paths, list) or not source_paths:
            raise ValueError("native component has no source paths")
        parsed.append(
            {
                "ecosystem": "native/vendored",
                "name": str(component["name"]),
                "version": str(component.get("version", "NOASSERTION")),
                "purl": str(component.get("purl", "NOASSERTION")),
                "license": str(component.get("license", "NOASSERTION")),
                "supplier": str(component.get("supplier", "NOASSERTION")),
                "download_location": str(
                    component.get("upstream_url", "NOASSERTION")
                ),
                "source_paths": [str(value) for value in source_paths],
                "revision": str(component.get("revision", "NOASSERTION")),
                "provenance_note": str(
                    component.get("provenance_note", "")
                ),
            }
        )
    return sorted(parsed, key=lambda value: (value["name"], value["version"]))


def _spdx_id(prefix: str, index: int, name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9.-]+", "-", name).strip("-") or "unnamed"
    return f"SPDXRef-{prefix}-{index}-{safe}"


def _root_version(path: Path) -> str:
    if not path.is_file():
        return "NOASSERTION"
    match = re.search(
        r"^version:\s*([^\s]+)",
        path.read_text(encoding="utf-8", errors="replace"),
        re.MULTILINE,
    )
    return match.group(1) if match else "NOASSERTION"


def build_sbom(root: Path, *, document_name: str, namespace: str) -> dict[str, Any]:
    root = root.resolve()
    file_paths = list(source_files(root))
    files = []
    file_ids: dict[str, str] = {}
    for index, path in enumerate(file_paths, start=1):
        relative = str(path.relative_to(root))
        spdx_id = _spdx_id("File", index, relative)
        file_ids[relative] = spdx_id
        files.append(
            {
                "SPDXID": spdx_id,
                "checksums": [
                    {"algorithm": "SHA256", "checksumValue": sha256_file(path)}
                ],
                "fileName": relative,
                "licenseConcluded": "NOASSERTION",
            }
        )

    dependencies: list[dict[str, Any]] = []
    dependencies.extend(parse_pubspec_lock(root / "pubspec.lock"))
    dependencies.extend(parse_gradle_dependencies(root))
    dependencies.extend(parse_podfile_lock(root / "ios/Podfile.lock"))
    dependencies.extend(
        parse_native_inventory(root / "third_party/native-components.json")
    )

    root_id = "SPDXRef-Package-HeptaGlasses"
    packages: list[dict[str, Any]] = [
        {
            "SPDXID": root_id,
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": True,
            "licenseConcluded": "BSD-2-Clause",
            "licenseDeclared": "BSD-2-Clause",
            "name": "hepta-glasses",
            "supplier": "Organization: Trillionnium Foundation",
            "versionInfo": _root_version(root / "pubspec.yaml"),
            "comment": "ecosystem=application",
        }
    ]
    relationships: list[dict[str, str]] = []
    for index, package in enumerate(dependencies, start=1):
        package_id = _spdx_id("Package", index, str(package["name"]))
        record: dict[str, Any] = {
            "SPDXID": package_id,
            "downloadLocation": package.get("download_location", "NOASSERTION"),
            "filesAnalyzed": False,
            "licenseConcluded": package.get("license", "NOASSERTION"),
            "licenseDeclared": package.get("license", "NOASSERTION"),
            "name": package["name"],
            "supplier": package.get("supplier", "NOASSERTION"),
            "versionInfo": package["version"],
            "comment": f"ecosystem={package['ecosystem']}",
        }
        purl = package.get("purl")
        if isinstance(purl, str) and purl != "NOASSERTION":
            record["externalRefs"] = [
                {
                    "referenceCategory": "PACKAGE-MANAGER",
                    "referenceLocator": purl,
                    "referenceType": "purl",
                }
            ]
        packages.append(record)
        relationships.append(
            {
                "spdxElementId": root_id,
                "relationshipType": "DEPENDS_ON",
                "relatedSpdxElement": package_id,
            }
        )
        for prefix in package.get("source_paths", []):
            normalized = str(prefix).rstrip("/") + "/"
            for relative, file_id in file_ids.items():
                if relative == str(prefix).rstrip("/") or relative.startswith(normalized):
                    relationships.append(
                        {
                            "spdxElementId": package_id,
                            "relationshipType": "CONTAINS",
                            "relatedSpdxElement": file_id,
                        }
                    )

    return {
        "SPDXID": "SPDXRef-DOCUMENT",
        "creationInfo": {"creators": ["Tool: hepta-source-sbom-2"]},
        "dataLicense": "CC0-1.0",
        "documentDescribes": [root_id],
        "documentNamespace": namespace,
        "files": files,
        "name": document_name,
        "packages": packages,
        "relationships": relationships,
        "spdxVersion": "SPDX-2.3",
    }


def package_ecosystems(document: Mapping[str, Any]) -> tuple[str, ...]:
    ecosystems = set()
    packages = document.get("packages")
    if isinstance(packages, list):
        for package in packages:
            if not isinstance(package, Mapping):
                continue
            comment = package.get("comment")
            if isinstance(comment, str) and comment.startswith("ecosystem="):
                value = comment.removeprefix("ecosystem=")
                if value != "application":
                    ecosystems.add(value)
    return tuple(sorted(ecosystems))


def canonical_digest(document: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            document,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
