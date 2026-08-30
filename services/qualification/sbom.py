"""Deterministic multi-ecosystem SPDX 2.3 source manifest."""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import quote

EXCLUDED = {".git", ".dart_tool", ".gradle", ".idea", ".swiftpm", "Pods", "build"}
EXTENSIONS = {
    ".c", ".cc", ".cmake", ".cpp", ".dart", ".gradle", ".h", ".json",
    ".kt", ".lock", ".m", ".md", ".pbxproj", ".plist", ".properties",
    ".py", ".sh", ".storyboard", ".swift", ".toml", ".xcconfig", ".xml",
    ".yaml", ".yml",
}
SPECIAL = {"CMakeLists.txt", "LICENSE", "Podfile", "pubspec.lock", "pubspec.yaml"}


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
        relative = path.relative_to(root)
        if any(part in EXCLUDED for part in relative.parts):
            continue
        if path.suffix.lower() in EXTENSIONS or path.name in SPECIAL:
            yield path


def _package(ecosystem: str, name: str, version: str, purl: str, purpose: str = "LIBRARY") -> dict[str, str]:
    return {"ecosystem": ecosystem, "name": name, "version": version, "purl": purl, "purpose": purpose}


def parse_pubspec_lock(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    result: list[dict[str, str]] = []
    current: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        name = re.match(r"^  ([A-Za-z0-9_.-]+):\s*$", line)
        if name:
            current = name.group(1)
            continue
        version = re.match(r'^    version:\s+"?([^"\s]+)"?\s*$', line)
        if current and version:
            value = version.group(1)
            result.append(_package("pub", current, value, f"pkg:pub/{quote(current, safe='')}@{quote(value, safe='')}"))
            current = None
    return result


def parse_podfile_lock(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    result: list[dict[str, str]] = []
    in_pods = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line == "PODS:":
            in_pods = True
            continue
        if in_pods and line and not line.startswith(" "):
            in_pods = False
        match = re.match(r"^  - ([^ (]+)(?: \(([^)]+)\))?", line) if in_pods else None
        if match:
            name, version = match.group(1), match.group(2) or "NOASSERTION"
            result.append(_package("cocoapods", name, version, f"pkg:cocoapods/{quote(name, safe='')}@{quote(version, safe='')}"))
        tool = re.match(r"^COCOAPODS:\s+(\S+)\s*$", line)
        if tool:
            version = tool.group(1)
            result.append(_package("build-tool", "cocoapods", version, f"pkg:gem/cocoapods@{quote(version, safe='')}", "BUILD_TOOL"))
    return result


def parse_gradle_packages(root: Path) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    plugin = re.compile(r'\bid\s+["\']([^"\']+)["\']\s+version\s+["\']([^"\']+)["\']')
    coordinate = re.compile(r"\b(?:api|classpath|implementation|testImplementation|androidTestImplementation|debugImplementation|releaseImplementation)\s+['\"]([^:'\"]+):([^:'\"]+):([^'\"]+)['\"]")
    for relative in ("android/settings.gradle", "android/build.gradle", "android/app/build.gradle"):
        path = root / relative
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for name, version in plugin.findall(text):
            result.append(_package("gradle-plugin", name, version, f"pkg:generic/{quote(name, safe='')}@{quote(version, safe='')}", "BUILD_TOOL"))
        for group, artifact, version in coordinate.findall(text):
            result.append(_package("maven", f"{group}:{artifact}", version, f"pkg:maven/{quote(group, safe='')}/{quote(artifact, safe='')}@{quote(version, safe='')}"))
        if relative.endswith("app/build.gradle"):
            cmake = re.search(r'\bversion\s*=\s*["\']([0-9][^"\']*)["\']', text)
            if cmake:
                version = cmake.group(1)
                result.append(_package("build-tool", "cmake", version, f"pkg:generic/cmake@{quote(version, safe='')}", "BUILD_TOOL"))
    wrapper = root / "android/gradle/wrapper/gradle-wrapper.properties"
    if wrapper.is_file():
        match = re.search(r"gradle-([0-9][0-9A-Za-z_.-]*)-(?:all|bin)\.zip", wrapper.read_text(encoding="utf-8"))
        if match:
            version = match.group(1)
            result.append(_package("build-tool", "gradle", version, f"pkg:generic/gradle@{quote(version, safe='')}", "BUILD_TOOL"))
    return result


def _component_files(root: Path, declared: list[str], excluded: list[str]) -> list[Path]:
    files: set[Path] = set()
    for relative in declared:
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as error:
            raise ValueError(f"third-party path escapes repository: {relative}") from error
        if candidate.is_file():
            files.add(candidate)
        elif candidate.is_dir():
            files.update(source_files(candidate))
        else:
            raise ValueError(f"third-party path does not exist: {relative}")
    exclusions = [(root / relative).resolve() for relative in excluded]
    return sorted(path for path in files if not any(path == item or item in path.parents for item in exclusions))


def _component_digest(root: Path, files: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in files:
        digest.update(str(path.relative_to(root)).replace("\\", "/").encode())
        digest.update(b"\0")
        digest.update(sha256_file(path).encode())
        digest.update(b"\n")
    return digest.hexdigest()


def parse_vendored_components(root: Path) -> tuple[list[dict[str, Any]], dict[str, tuple[str, ...]]]:
    path = root / "third_party/components.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema_version") != 1 or not isinstance(document.get("components"), list):
        raise ValueError("invalid third-party component manifest")
    packages: list[dict[str, Any]] = []
    ownership: dict[str, tuple[str, ...]] = {}
    seen: set[str] = set()
    for raw in document["components"]:
        if not isinstance(raw, Mapping):
            raise ValueError("third-party component must be an object")
        name = raw.get("name")
        paths = raw.get("paths")
        excluded = raw.get("exclude_paths", [])
        if not isinstance(name, str) or not name or name in seen or not isinstance(paths, list) or not paths or not all(isinstance(item, str) for item in paths) or not isinstance(excluded, list) or not all(isinstance(item, str) for item in excluded):
            raise ValueError(f"invalid third-party component: {name!r}")
        for field in ("supplier", "license", "download_location"):
            if not isinstance(raw.get(field), str) or not raw[field]:
                raise ValueError(f"{name} has no {field}")
        seen.add(name)
        files = _component_files(root, paths, excluded)
        if not files:
            raise ValueError(f"third-party component has no files: {name}")
        digest = _component_digest(root, files)
        ownership[name] = tuple(str(item.relative_to(root)).replace("\\", "/") for item in files)
        packages.append({**_package("vendored", name, f"sha256:{digest}", f"pkg:generic/{quote(name, safe='')}@{digest}"), "supplier": raw["supplier"], "license": raw["license"], "download_location": raw["download_location"], "checksum": digest})
    return packages, ownership


def _root_identity(root: Path) -> tuple[str, str]:
    text = (root / "pubspec.yaml").read_text(encoding="utf-8")
    name = re.search(r"(?m)^name:\s*([A-Za-z0-9_.-]+)\s*$", text)
    version = re.search(r"(?m)^version:\s*([^\s#]+)\s*$", text)
    return (name.group(1) if name else "hepta-glasses", version.group(1) if version else "NOASSERTION")


def build_sbom(root: Path, *, document_name: str, namespace: str) -> dict[str, Any]:
    root = root.resolve()
    disk = list(source_files(root))
    files = [{"SPDXID": f"SPDXRef-File-{index}", "fileName": str(path.relative_to(root)).replace("\\", "/"), "checksums": [{"algorithm": "SHA256", "checksumValue": sha256_file(path)}], "licenseConcluded": "NOASSERTION"} for index, path in enumerate(disk, 1)]
    file_ids = {item["fileName"]: item["SPDXID"] for item in files}
    vendored, ownership = parse_vendored_components(root)
    raw = parse_pubspec_lock(root / "pubspec.lock") + parse_podfile_lock(root / "ios/Podfile.lock") + parse_gradle_packages(root) + vendored
    dependencies = list({(item["ecosystem"], item["name"], item["version"]): item for item in raw}.values())
    dependencies.sort(key=lambda item: (item["ecosystem"], item["name"], item["version"]))
    name, version = _root_identity(root)
    root_id = "SPDXRef-Package-Root"
    packages: list[dict[str, Any]] = [{"SPDXID": root_id, "name": name, "versionInfo": version, "downloadLocation": "NOASSERTION", "filesAnalyzed": True, "licenseConcluded": "BSD-2-Clause", "licenseDeclared": "BSD-2-Clause", "supplier": "Organization: TrillionniumFoundation", "primaryPackagePurpose": "APPLICATION", "comment": "ecosystem: application"}]
    ids: dict[tuple[str, str, str], str] = {}
    for index, item in enumerate(dependencies, 1):
        key = (item["ecosystem"], item["name"], item["version"])
        package_id = f"SPDXRef-Package-{index}-{re.sub(r'[^A-Za-z0-9.-]+', '-', item['name'])[:48]}"
        ids[key] = package_id
        package: dict[str, Any] = {"SPDXID": package_id, "name": item["name"], "versionInfo": item["version"], "downloadLocation": item.get("download_location", "NOASSERTION"), "filesAnalyzed": item["ecosystem"] == "vendored", "licenseConcluded": item.get("license", "NOASSERTION"), "licenseDeclared": item.get("license", "NOASSERTION"), "supplier": item.get("supplier", "NOASSERTION"), "primaryPackagePurpose": item.get("purpose", "LIBRARY"), "comment": f"ecosystem: {item['ecosystem']}", "externalRefs": [{"referenceCategory": "PACKAGE-MANAGER", "referenceType": "purl", "referenceLocator": item["purl"]}]}
        if item.get("checksum"):
            package["checksums"] = [{"algorithm": "SHA256", "checksumValue": item["checksum"]}]
        packages.append(package)
    relationships = [{"spdxElementId": "SPDXRef-DOCUMENT", "relationshipType": "DESCRIBES", "relatedSpdxElement": root_id}]
    relationships.extend({"spdxElementId": root_id, "relationshipType": "CONTAINS", "relatedSpdxElement": item["SPDXID"]} for item in files)
    for item in dependencies:
        key = (item["ecosystem"], item["name"], item["version"])
        package_id = ids[key]
        relationships.append({"spdxElementId": root_id, "relationshipType": "DEPENDS_ON", "relatedSpdxElement": package_id})
        if item["ecosystem"] == "vendored":
            for relative in ownership[item["name"]]:
                if relative not in file_ids:
                    raise ValueError(f"vendored source omitted from SBOM: {relative}")
                relationships.append({"spdxElementId": package_id, "relationshipType": "CONTAINS", "relatedSpdxElement": file_ids[relative]})
    return {"SPDXID": "SPDXRef-DOCUMENT", "spdxVersion": "SPDX-2.3", "dataLicense": "CC0-1.0", "name": document_name, "documentNamespace": namespace, "creationInfo": {"creators": ["Tool: hepta-source-sbom-2"]}, "files": files, "packages": packages, "relationships": relationships}


def inventory_summary(document: Mapping[str, Any]) -> dict[str, Any]:
    packages = document.get("packages") if isinstance(document.get("packages"), list) else []
    files = document.get("files") if isinstance(document.get("files"), list) else []
    relationships = document.get("relationships") if isinstance(document.get("relationships"), list) else []
    counts: Counter[str] = Counter()
    for package in packages:
        if isinstance(package, Mapping) and isinstance(package.get("comment"), str) and package["comment"].startswith("ecosystem: "):
            counts[package["comment"].removeprefix("ecosystem: ")] += 1
    return {"ecosystem_counts": dict(sorted(counts.items())), "file_count": len(files), "package_count": len(packages), "relationship_count": len(relationships), "vendored_component_count": counts["vendored"]}


def canonical_digest(document: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(document, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()).hexdigest()
