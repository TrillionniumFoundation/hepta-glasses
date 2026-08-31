#!/usr/bin/env python3
"""Apply the second G7 source-hardening wave.

This pass closes repository-actionable races and reference-service deployment
hazards without pretending to provide physical-device or production-service
evidence. It is idempotent and only targets the G7 candidate branch.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
G4 = "origin/codex/hepta-glasses-source-closure-g4"


def replace(path: str, old: str, new: str, *, required: bool = True) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        if required:
            raise RuntimeError(f"pattern missing in {path}: {old[:100]!r}")
        return
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def import_from_g4(path: str) -> None:
    probe = subprocess.run(
        ["git", "cat-file", "-e", f"{G4}:{path}"],
        cwd=ROOT,
        check=False,
    )
    if probe.returncode == 0 and not (ROOT / path).exists():
        subprocess.run(
            ["git", "checkout", G4, "--", path],
            cwd=ROOT,
            check=True,
        )


def add_synchronization(path: str, class_name: str, methods: tuple[str, ...]) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if "import functools\n" not in text:
        text = text.replace(
            "from __future__ import annotations\n",
            "from __future__ import annotations\n\nimport functools\nimport threading\n",
            1,
        )
    helper = '''\n\ndef _synchronized(method):\n    @functools.wraps(method)\n    def wrapped(self, *args, **kwargs):\n        with self._lock:\n            return method(self, *args, **kwargs)\n\n    return wrapped\n'''
    marker = f"\n\nclass {class_name}"
    if "def _synchronized(method):" not in text:
        if marker not in text:
            raise RuntimeError(f"class marker missing in {path}: {class_name}")
        text = text.replace(marker, helper + marker, 1)
    class_start = text.index(f"class {class_name}")
    for method in methods:
        needle = f"\n    def {method}("
        position = text.find(needle, class_start)
        if position < 0:
            continue
        decorator = "\n    @_synchronized"
        if text[max(class_start, position - 40):position].endswith(decorator):
            continue
        text = text[:position] + decorator + text[position:]
    target.write_text(text, encoding="utf-8")


def patch_realtime() -> None:
    path = "services/control_plane/realtime.py"
    add_synchronization(
        path,
        "RealtimeSessionBroker",
        ("issue_ticket", "activate", "transition", "interrupt", "revoke", "get"),
    )
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    anchor = "        self._consumed_ticket_ids: set[str] = set()\n"
    if "        self._lock = threading.RLock()\n" not in text:
        if anchor not in text:
            raise RuntimeError("RealtimeSessionBroker initialization anchor missing")
        text = text.replace(
            anchor,
            anchor + "        self._lock = threading.RLock()\n",
            1,
        )
    target.write_text(text, encoding="utf-8")


def patch_capabilities() -> None:
    path = "services/control_plane/capabilities.py"
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if "import functools\n" not in text:
        text = text.replace(
            "from __future__ import annotations\n",
            "from __future__ import annotations\n\nimport functools\nimport threading\n",
            1,
        )
    helper = '''\n\ndef _synchronized(method):\n    @functools.wraps(method)\n    def wrapped(self, *args, **kwargs):\n        with self._lock:\n            return method(self, *args, **kwargs)\n\n    return wrapped\n'''
    if "def _synchronized(method):" not in text:
        marker = "\n\nclass AuditJournal:"
        if marker not in text:
            raise RuntimeError("Capability AuditJournal marker missing")
        text = text.replace(marker, helper + marker, 1)

    def decorate(class_name: str, methods: tuple[str, ...]) -> None:
        nonlocal text
        start = text.index(f"class {class_name}")
        next_class = text.find("\n\nclass ", start + 1)
        end = len(text) if next_class < 0 else next_class
        for method in methods:
            needle = f"\n    def {method}("
            position = text.find(needle, start, end)
            if position < 0:
                continue
            if text[max(start, position - 40):position].endswith("\n    @_synchronized"):
                continue
            text = text[:position] + "\n    @_synchronized" + text[position:]
            end += len("\n    @_synchronized")

    for class_name, methods in (
        ("AuditJournal", ("append", "verify")),
        ("CapabilityGateway", ("register", "execute")),
    ):
        decorate(class_name, methods)

    audit_anchor = "        self.entries: list[dict[str, Any]] = []\n"
    if "class AuditJournal:" in text:
        audit_start = text.index("class AuditJournal:")
        audit_end = text.find("\n\nclass ", audit_start + 1)
        audit_block = text[audit_start:audit_end]
        if "self._lock = threading.RLock()" not in audit_block:
            if audit_anchor not in text:
                raise RuntimeError("Capability AuditJournal init anchor missing")
            text = text.replace(
                audit_anchor,
                audit_anchor + "        self._lock = threading.RLock()\n",
                1,
            )
    gateway_anchor = "        self._consumed_leases: set[str] = set()\n"
    gateway_start = text.index("class CapabilityGateway:")
    gateway_end = text.find("\n\nclass ", gateway_start + 1)
    gateway_block = text[gateway_start:gateway_end]
    if "self._lock = threading.RLock()" not in gateway_block:
        if gateway_anchor not in text:
            raise RuntimeError("CapabilityGateway init anchor missing")
        text = text.replace(
            gateway_anchor,
            gateway_anchor + "        self._lock = threading.RLock()\n",
            1,
        )
    target.write_text(text, encoding="utf-8")


def patch_skill_package_integrity() -> None:
    path = ROOT / "services/skills/registry.py"
    text = path.read_text(encoding="utf-8")
    if "from pathlib import Path\n" not in text:
        import_marker = "import hmac\n"
        if import_marker not in text:
            raise RuntimeError("skill registry import anchor missing")
        text = text.replace(import_marker, import_marker + "from pathlib import Path\n", 1)
    helper = '''\n\ndef package_sha256(path: str | Path) -> str:\n    digest = hashlib.sha256()\n    with Path(path).open("rb") as handle:\n        for chunk in iter(lambda: handle.read(1024 * 1024), b""):\n            digest.update(chunk)\n    return digest.hexdigest()\n'''
    if "def package_sha256(" not in text:
        marker = "\n\nclass SkillTrustStore:"
        if marker not in text:
            raise RuntimeError("SkillTrustStore marker missing")
        text = text.replace(marker, helper + marker, 1)
    method = '''    def install_package(\n        self,\n        manifest: SkillManifest,\n        *,\n        package_path: str | Path,\n        consented_capabilities: frozenset[str],\n        consented_data_classes: frozenset[str],\n        consented_network_domains: frozenset[str],\n        now: int,\n    ) -> InstalledSkill:\n        actual_digest = package_sha256(package_path)\n        if not hmac.compare_digest(actual_digest, manifest.package_digest):\n            raise SkillError("skill_package_digest_mismatch")\n        return self.install(\n            manifest,\n            consented_capabilities=consented_capabilities,\n            consented_data_classes=consented_data_classes,\n            consented_network_domains=consented_network_domains,\n            now=now,\n        )\n\n'''
    if "    def install_package(" not in text:
        marker = "    def install(\n"
        position = text.find(marker, text.index("class SkillRegistry:"))
        if position < 0:
            raise RuntimeError("SkillRegistry.install marker missing")
        text = text[:position] + method + text[position:]
    path.write_text(text, encoding="utf-8")


def patch_codex_policy() -> None:
    path = ROOT / "services/codex_worker/worker.py"
    text = path.read_text(encoding="utf-8")
    field_anchor = "    executable: str\n"
    if "    network_access_default: bool = False\n" not in text:
        if field_anchor not in text:
            raise RuntimeError("WorkerPolicy field anchor missing")
        text = text.replace(
            field_anchor,
            field_anchor + "    network_access_default: bool = False\n",
            1,
        )
    load_anchor = '            executable=str(document["executable"]),\n'
    if 'network_access_default=bool(document.get("network_access_default", False))' not in text:
        if load_anchor not in text:
            raise RuntimeError("WorkerPolicy.load anchor missing")
        text = text.replace(
            load_anchor,
            load_anchor
            + '            network_access_default=bool(\n'
            + '                document.get("network_access_default", False)\n'
            + '            ),\n',
            1,
        )
    size_anchor = '''        last_message = (\n            output_path.read_text(encoding="utf-8", errors="replace")\n            if output_path.is_file()\n            else ""\n        )\n'''
    size_replacement = '''        if (\n            output_path.is_file()\n            and output_path.stat().st_size > policy.maximum_output_bytes\n        ):\n            raise WorkerError("codex_output_too_large")\n        last_message = (\n            output_path.read_text(encoding="utf-8", errors="replace")\n            if output_path.is_file()\n            else ""\n        )\n        if (\n            len(stdout)\n            + len(stderr)\n            + len(last_message.encode("utf-8", errors="replace"))\n            > policy.maximum_output_bytes\n        ):\n            raise WorkerError("codex_output_too_large")\n'''
    if size_replacement not in text:
        if size_anchor not in text:
            raise RuntimeError("Codex output-path anchor missing")
        text = text.replace(size_anchor, size_replacement, 1)
    path.write_text(text, encoding="utf-8")


def patch_model_gateway() -> None:
    path = ROOT / "services/model_gateway/app.py"
    text = path.read_text(encoding="utf-8")
    if "import ipaddress\n" not in text:
        text = text.replace("import hmac\n", "import hmac\nimport ipaddress\n", 1)
    helper = '''\n\ndef is_loopback_host(host: str) -> bool:\n    if host.lower() == "localhost":\n        return True\n    try:\n        return ipaddress.ip_address(host).is_loopback\n    except ValueError:\n        return False\n'''
    if "def is_loopback_host(" not in text:
        marker = "\n\ndef authorize("
        if marker not in text:
            raise RuntimeError("model gateway authorize marker missing")
        text = text.replace(marker, helper + marker, 1)
    guard = '''    if (\n        not os.environ.get("HEPTA_GATEWAY_DEV_TOKEN")\n        and not is_loopback_host(args.host)\n    ):\n        raise SystemExit(\n            "HEPTA_GATEWAY_DEV_TOKEN is required for non-loopback binding"\n        )\n'''
    if "HEPTA_GATEWAY_DEV_TOKEN is required for non-loopback binding" not in text:
        anchor = "    args = parser.parse_args()\n"
        if anchor not in text:
            raise RuntimeError("model gateway main args anchor missing")
        text = text.replace(anchor, anchor + guard, 1)
    path.write_text(text, encoding="utf-8")


def patch_release_credential_gate() -> None:
    path = ROOT / "services/qualification/release_gate.py"
    text = path.read_text(encoding="utf-8")
    anchor = '''        production = bundle.get("production")\n        production = production if isinstance(production, Mapping) else {}\n'''
    addition = anchor + '''        credential_incident = bundle.get("credential_incident")\n        credential_incident = (\n            credential_incident\n            if isinstance(credential_incident, Mapping)\n            else {}\n        )\n'''
    if "credential_incident = bundle.get" not in text:
        if anchor not in text:
            raise RuntimeError("release gate production anchor missing")
        text = text.replace(anchor, addition, 1)
    return_anchor = '''            "production_capabilities": production.get("capabilities") == "verified",\n'''
    return_addition = return_anchor + '''            "historical_credential_revoked": (\n                credential_incident.get("provider_rotation_or_revocation")\n                == "verified"\n            ),\n'''
    if '"historical_credential_revoked"' not in text:
        if return_anchor not in text:
            raise RuntimeError("release gate return anchor missing")
        text = text.replace(return_anchor, return_addition, 1)
    path.write_text(text, encoding="utf-8")

    template = ROOT / "evidence/templates/product-release-bundle.template.json"
    if template.exists():
        document = template.read_text(encoding="utf-8")
        if '"credential_incident"' not in document:
            first = document.find("{")
            document = (
                document[: first + 1]
                + '\n  "credential_incident": {\n'
                + '    "provider_rotation_or_revocation": "unverified"\n'
                + "  },"
                + document[first + 1 :]
            )
            template.write_text(document, encoding="utf-8")


def add_tests() -> None:
    (ROOT / "services/skills/test_package_integrity_g7.py").write_text(
        '''from __future__ import annotations\n\nimport hashlib\nimport tempfile\nimport unittest\nfrom pathlib import Path\n\nfrom services.skills.registry import package_sha256\n\n\nclass PackageIntegrityTests(unittest.TestCase):\n    def test_streamed_package_digest_matches_sha256(self) -> None:\n        with tempfile.TemporaryDirectory() as directory:\n            path = Path(directory) / "skill.pkg"\n            payload = b"hepta-skill-package" * 4096\n            path.write_bytes(payload)\n            self.assertEqual(\n                package_sha256(path),\n                hashlib.sha256(payload).hexdigest(),\n            )\n\n\nif __name__ == "__main__":\n    unittest.main()\n''',
        encoding="utf-8",
    )
    (ROOT / "services/model_gateway/test_binding_guard_g7.py").write_text(
        '''from __future__ import annotations\n\nimport unittest\n\nfrom services.model_gateway.app import is_loopback_host\n\n\nclass BindingGuardTests(unittest.TestCase):\n    def test_only_loopback_addresses_are_implicitly_development_safe(self) -> None:\n        self.assertTrue(is_loopback_host("127.0.0.1"))\n        self.assertTrue(is_loopback_host("::1"))\n        self.assertTrue(is_loopback_host("localhost"))\n        self.assertFalse(is_loopback_host("0.0.0.0"))\n        self.assertFalse(is_loopback_host("gateway.internal"))\n\n\nif __name__ == "__main__":\n    unittest.main()\n''',
        encoding="utf-8",
    )


def cleanup_one_shot_workflows() -> None:
    workflow_dir = ROOT / ".github/workflows"
    keep = {
        "ci.yml",
        "g7-synthesis.yml",
        "g7-stage.yml",
        "g7-repair.yml",
        "g7-wave2.yml",
        "g7-qualify.yml",
    }
    for path in workflow_dir.glob("*.yml"):
        if path.name in keep:
            continue
        if path.name.startswith(("g5-", "g6-", "autofix-")):
            path.unlink()


def update_current_state() -> None:
    path = ROOT / "docs/CURRENT_STATE.md"
    text = path.read_text(encoding="utf-8")
    section = '''\n## G7 synthesis status\n\nThe G7 branch is the sole convergence candidate. It combines the stricter G4\nnative/mobile fixes with the G5/G6 audit, SBOM, history, and release-evidence\nwork. Repository-actionable closure requires one unchanged exact head with all\nrequired jobs passing. A historical credential fingerprint remains a product\nrelease blocker until provider-side rotation or revocation is independently\nverified; it is not hidden or converted into a current-tree finding.\n\nReference control-plane locks close in-process deterministic races. Multi-node\nproduction atomicity still requires the deployed transactional datastore and is\ntherefore part of the E5 control-plane gate.\n'''
    if "## G7 synthesis status" not in text:
        text += section
    path.write_text(text, encoding="utf-8")


def main() -> int:
    import_from_g4("docs/operations/CREDENTIAL_INCIDENT_RUNBOOK.md")
    import_from_g4("evidence/templates/credential-incident-closure.template.json")
    patch_realtime()
    patch_capabilities()
    patch_skill_package_integrity()
    patch_codex_policy()
    patch_model_gateway()
    patch_release_credential_gate()
    add_tests()
    cleanup_one_shot_workflows()
    update_current_state()
    for path in (
        ROOT / "tools/apply_g7_wave2.py",
        ROOT / "tools/apply_g7_repair.py",
        ROOT / "tools/apply_g7_synthesis.py",
    ):
        if path.exists():
            path.chmod(0o755)
    subprocess.run(["git", "add", "-A"], cwd=ROOT, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
