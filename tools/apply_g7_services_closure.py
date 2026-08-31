#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def worker_source() -> str:
    return r'''#!/usr/bin/env python3
"""Bounded non-interactive Codex worker for Hepta Glasses source tasks."""
from __future__ import annotations
import argparse
import json
import os
import re
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

POLICY_PATH = Path(__file__).with_name("policy.json")
TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

class WorkerError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code

@dataclass(frozen=True)
class WorkerPolicy:
    allowed_sandboxes: tuple[str, ...]
    maximum_prompt_characters: int
    maximum_timeout_seconds: int
    maximum_output_bytes: int
    executable: str
    network_access_default: bool = True
    network_guard: tuple[str, ...] = ()

    @classmethod
    def load(cls, path: Path = POLICY_PATH) -> "WorkerPolicy":
        document = json.loads(path.read_text(encoding="utf-8"))
        policy = cls(
            allowed_sandboxes=tuple(document["allowed_sandboxes"]),
            maximum_prompt_characters=int(document["maximum_prompt_characters"]),
            maximum_timeout_seconds=int(document["maximum_timeout_seconds"]),
            maximum_output_bytes=int(document["maximum_output_bytes"]),
            executable=str(document["executable"]),
            network_access_default=bool(document.get("network_access_default", False)),
            network_guard=tuple(str(value) for value in document.get("network_guard", ["unshare", "--net", "--"])),
        )
        if not policy.network_access_default and not policy.network_guard:
            raise WorkerError("network_guard_required")
        if not policy.allowed_sandboxes or policy.maximum_prompt_characters < 1 or policy.maximum_timeout_seconds < 1 or policy.maximum_output_bytes < 1 or not policy.executable:
            raise WorkerError("worker_policy_invalid")
        return policy

@dataclass(frozen=True)
class CodexTask:
    task_id: str
    prompt: str
    workspace: Path
    sandbox: str
    timeout_seconds: int

def _mapping(document: Any) -> Mapping[str, Any]:
    if not isinstance(document, Mapping):
        raise WorkerError("task_must_be_object")
    return document

def validate_task(document: Any, *, workspace_root: Path, policy: WorkerPolicy) -> CodexTask:
    value = _mapping(document)
    if set(value) - {"task_id", "prompt", "workspace", "sandbox", "timeout_seconds"}:
        raise WorkerError("unknown_task_fields")
    task_id = value.get("task_id")
    if not isinstance(task_id, str) or not TASK_ID_RE.fullmatch(task_id):
        raise WorkerError("invalid_task_id")
    prompt = value.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise WorkerError("prompt_required")
    prompt = prompt.strip()
    if len(prompt) > policy.maximum_prompt_characters:
        raise WorkerError("prompt_too_large")
    sandbox = value.get("sandbox", "read-only")
    if sandbox not in policy.allowed_sandboxes:
        raise WorkerError("sandbox_not_allowed")
    timeout_seconds = value.get("timeout_seconds", 900)
    if not isinstance(timeout_seconds, int) or timeout_seconds < 1 or timeout_seconds > policy.maximum_timeout_seconds:
        raise WorkerError("invalid_timeout")
    raw_workspace = value.get("workspace")
    if not isinstance(raw_workspace, str) or not raw_workspace:
        raise WorkerError("workspace_required")
    root = workspace_root.resolve(strict=True)
    workspace = (root / raw_workspace).resolve(strict=True)
    if workspace != root and root not in workspace.parents:
        raise WorkerError("workspace_outside_root")
    if not workspace.is_dir():
        raise WorkerError("workspace_not_directory")
    return CodexTask(task_id=task_id, prompt=prompt, workspace=workspace, sandbox=sandbox, timeout_seconds=timeout_seconds)

def build_command(task: CodexTask, *, policy: WorkerPolicy, output_path: Path) -> list[str]:
    command = [policy.executable, "exec", "--ephemeral", "--json", "--sandbox", task.sandbox, "--cd", str(task.workspace), "--output-last-message", str(output_path), "-"]
    if not policy.network_access_default:
        if not policy.network_guard:
            raise WorkerError("network_guard_required")
        return [*policy.network_guard, *command]
    return command

def bounded_environment(source: Mapping[str, str] | None = None) -> dict[str, str]:
    source = source or os.environ
    allowed_names = {"PATH", "HOME", "CODEX_HOME", "LANG", "LC_ALL", "SSL_CERT_FILE", "SSL_CERT_DIR"}
    return {name: source[name] for name in allowed_names if name in source}

def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (AttributeError, ProcessLookupError, PermissionError):
        process.terminate()
    try:
        process.wait(timeout=2)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (AttributeError, ProcessLookupError, PermissionError):
        process.kill()
    process.wait(timeout=2)

def _bounded_read(path: Path, maximum: int) -> str:
    if not path.exists():
        return ""
    if path.stat().st_size > maximum:
        raise WorkerError("codex_output_too_large")
    return path.read_bytes().decode("utf-8", errors="replace")

def run_task(task: CodexTask, *, policy: WorkerPolicy, dry_run: bool = False) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix=f"hepta-codex-{task.task_id}-") as temp_dir:
        temp_root = Path(temp_dir)
        output_path = temp_root / "last-message.txt"
        stdout_path = temp_root / "stdout.jsonl"
        stderr_path = temp_root / "stderr.log"
        command = build_command(task, policy=policy, output_path=output_path)
        if dry_run:
            return {"task_id": task.task_id, "command": command, "workspace": str(task.workspace), "sandbox": task.sandbox, "network_isolated": not policy.network_access_default}
        try:
            with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
                process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=stdout, stderr=stderr, cwd=task.workspace, env=bounded_environment(), start_new_session=True)
                assert process.stdin is not None
                process.stdin.write(task.prompt.encode("utf-8"))
                process.stdin.close()
                deadline = time.monotonic() + task.timeout_seconds
                while process.poll() is None:
                    total_size = sum(path.stat().st_size if path.exists() else 0 for path in (stdout_path, stderr_path, output_path))
                    if total_size > policy.maximum_output_bytes:
                        _terminate_process(process)
                        raise WorkerError("codex_output_too_large")
                    if time.monotonic() >= deadline:
                        _terminate_process(process)
                        raise WorkerError("codex_timeout")
                    time.sleep(0.02)
                return_code = process.wait()
        except WorkerError:
            raise
        except OSError as error:
            raise WorkerError("codex_start_failed") from error
        sizes = [path.stat().st_size if path.exists() else 0 for path in (stdout_path, stderr_path, output_path)]
        if sum(sizes) > policy.maximum_output_bytes:
            raise WorkerError("codex_output_too_large")
        remaining = policy.maximum_output_bytes
        event_stream = _bounded_read(stdout_path, remaining)
        remaining -= len(event_stream.encode("utf-8", errors="replace"))
        diagnostic = _bounded_read(stderr_path, max(remaining, 0))
        remaining -= len(diagnostic.encode("utf-8", errors="replace"))
        last_message = _bounded_read(output_path, max(remaining, 0))
        return {"task_id": task.task_id, "return_code": return_code, "last_message": last_message, "event_stream": event_stream, "diagnostic": diagnostic, "network_isolated": not policy.network_access_default}

def load_document(path: Path | None) -> Any:
    if path is None:
        return json.load(os.sys.stdin)
    return json.loads(path.read_text(encoding="utf-8"))

def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--task", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        policy = WorkerPolicy.load()
        task = validate_task(load_document(args.task), workspace_root=args.workspace_root, policy=policy)
        result = run_task(task, policy=policy, dry_run=args.dry_run)
    except (WorkerError, json.JSONDecodeError, OSError) as error:
        code = error.code if isinstance(error, WorkerError) else "invalid_worker_input"
        print(json.dumps({"ok": False, "error": code}, separators=(",", ":")))
        return 2
    print(json.dumps({"ok": True, "result": result}, separators=(",", ":")))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
'''


def realtime_test_source() -> str:
    return r'''from __future__ import annotations
import inspect
import unittest
from concurrent.futures import ThreadPoolExecutor
from services.control_plane import test_realtime as existing_tests
from services.control_plane.realtime import RealtimeError, RealtimeSessionBroker

def _fixture_case() -> unittest.TestCase:
    candidates = [value for value in vars(existing_tests).values() if inspect.isclass(value) and issubclass(value, unittest.TestCase) and value is not unittest.TestCase and "setUp" in value.__dict__]
    if not candidates:
        raise AssertionError("realtime fixture TestCase not found")
    methods = unittest.defaultTestLoader.getTestCaseNames(candidates[0])
    case = candidates[0](methods[0])
    case.setUp()
    return case

class RealtimeConcurrencyTest(unittest.TestCase):
    def test_bootstrap_ticket_is_consumed_atomically(self) -> None:
        fixture = _fixture_case()
        broker = next(value for value in vars(fixture).values() if isinstance(value, RealtimeSessionBroker))
        ticket = None
        for value in vars(fixture).values():
            if not isinstance(value, str):
                continue
            try:
                ticket = broker.issue_ticket(access_token=value, requested_scopes={"audio.input"}, provider_profile=next(iter(broker.allowed_provider_profiles)), ttl_seconds=60)
                break
            except Exception:
                continue
        self.assertIsNotNone(ticket)
        assert ticket is not None
        def activate() -> str:
            try:
                return broker.activate(ticket.bootstrap_token).state.value
            except RealtimeError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(pool.map(lambda _: activate(), range(8)))
        self.assertEqual(outcomes.count("connecting"), 1)
        self.assertEqual(outcomes.count("bootstrap_ticket_replayed") + outcomes.count("realtime_session_already_activated"), 7)

if __name__ == "__main__":
    unittest.main()
'''


def capability_test_source() -> str:
    return r'''from __future__ import annotations
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Mapping
from services.control_plane.capabilities import AuditJournal, CapabilityGateway, CapabilityRequest, CapabilitySpec, DecisionLease, RiskTier, TrustClass, canonical_digest

class CountingAdapter:
    def __init__(self) -> None:
        self.count = 0
        self.active = 0
        self.maximum_active = 0
        self._lock = threading.Lock()
    def execute(self, request: CapabilityRequest) -> Mapping[str, Any]:
        with self._lock:
            self.count += 1
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)
        time.sleep(0.05)
        with self._lock:
            self.active -= 1
        return {"authoritative": True, "request_id": request.request_id}
    def reconcile(self, request: CapabilityRequest, external_id: str) -> Mapping[str, Any]:
        return {"authoritative": True, "external_id": external_id}

class CapabilityConcurrencyTest(unittest.TestCase):
    def _gateway(self) -> tuple[CapabilityGateway, CountingAdapter]:
        adapter = CountingAdapter()
        gateway = CapabilityGateway(journal=AuditJournal(), clock=lambda: 100)
        gateway.register(CapabilitySpec(name="reminder.create", risk=RiskTier.R2, mutating=True, required_fields=frozenset({"title"}), reconciliation_supported=True), adapter)
        return gateway, adapter
    def _request(self, identifier: str, key: str) -> CapabilityRequest:
        return CapabilityRequest(request_id=identifier, task_id="task-1", subject="user-1", device_id="device-1", name="reminder.create", arguments={"title": "Call Alice"}, idempotency_key=key, deadline=200, origin=TrustClass.USER)
    def _lease(self, identifier: str) -> DecisionLease:
        return DecisionLease(lease_id=identifier, subject="user-1", device_id="device-1", task_id="task-1", action="reminder.create", argument_digest=canonical_digest({"title": "Call Alice"}), expires_at=200, biometric_verified=False)
    def test_same_idempotency_key_executes_effect_once(self) -> None:
        gateway, adapter = self._gateway()
        request = self._request("request-1", "stable-key")
        lease = self._lease("lease-1")
        with ThreadPoolExecutor(max_workers=2) as pool:
            receipts = list(pool.map(lambda _: gateway.execute(request, lease=lease), range(2)))
        self.assertEqual(adapter.count, 1)
        self.assertEqual([receipt.status for receipt in receipts], ["succeeded"] * 2)
        self.assertEqual(sum(receipt.replayed for receipt in receipts), 1)
        gateway.journal.verify()
    def test_different_keys_are_not_globally_serialized(self) -> None:
        gateway, adapter = self._gateway()
        pairs = [(self._request(f"request-{index}", f"key-{index}"), self._lease(f"lease-{index}")) for index in range(2)]
        with ThreadPoolExecutor(max_workers=2) as pool:
            receipts = list(pool.map(lambda pair: gateway.execute(pair[0], lease=pair[1]), pairs))
        self.assertEqual([receipt.status for receipt in receipts], ["succeeded"] * 2)
        self.assertEqual(adapter.count, 2)
        self.assertGreaterEqual(adapter.maximum_active, 2)
        gateway.journal.verify()
    def test_single_use_lease_cannot_race_across_different_keys(self) -> None:
        gateway, adapter = self._gateway()
        lease = self._lease("shared-lease")
        requests = [self._request(f"request-{index}", f"key-{index}") for index in range(2)]
        with ThreadPoolExecutor(max_workers=2) as pool:
            receipts = list(pool.map(lambda request: gateway.execute(request, lease=lease), requests))
        self.assertEqual(adapter.count, 1)
        self.assertEqual(sorted(receipt.status for receipt in receipts), ["denied", "succeeded"])
        self.assertIn("decision_lease_consumed", [receipt.result.get("reason") for receipt in receipts])
        gateway.journal.verify()

if __name__ == "__main__":
    unittest.main()
'''


def worker_test_source() -> str:
    return r'''from __future__ import annotations
import os
import tempfile
import unittest
from pathlib import Path
from services.codex_worker.worker import CodexTask, WorkerError, WorkerPolicy, build_command, run_task

class CodexWorkerIsolationTest(unittest.TestCase):
    def test_network_guard_wraps_codex_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            task = CodexTask(task_id="guard", prompt="inspect", workspace=workspace, sandbox="read-only", timeout_seconds=10)
            policy = WorkerPolicy(allowed_sandboxes=("read-only",), maximum_prompt_characters=100, maximum_timeout_seconds=10, maximum_output_bytes=1024, executable="codex", network_access_default=False, network_guard=("unshare", "--net", "--"))
            command = build_command(task, policy=policy, output_path=workspace / "message.txt")
            self.assertEqual(command[:3], ["unshare", "--net", "--"])
            self.assertEqual(command[3:6], ["codex", "exec", "--ephemeral"])
    @unittest.skipIf(os.name == "nt", "process-group enforcement is POSIX-specific")
    def test_streaming_output_limit_terminates_worker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            executable = workspace / "fake-codex"
            executable.write_text("#!/usr/bin/env python3\nimport sys, time\nsys.stdout.write('x' * 100000)\nsys.stdout.flush()\ntime.sleep(5)\n", encoding="utf-8")
            executable.chmod(0o755)
            task = CodexTask(task_id="bounded", prompt="inspect", workspace=workspace, sandbox="read-only", timeout_seconds=5)
            policy = WorkerPolicy(allowed_sandboxes=("read-only",), maximum_prompt_characters=100, maximum_timeout_seconds=10, maximum_output_bytes=1024, executable=str(executable), network_access_default=True)
            with self.assertRaises(WorkerError) as raised:
                run_task(task, policy=policy)
            self.assertEqual(raised.exception.code, "codex_output_too_large")

if __name__ == "__main__":
    unittest.main()
'''


def patch_realtime() -> None:
    path = ROOT / "services/control_plane/realtime.py"
    text = path.read_text(encoding="utf-8")
    if "import threading" not in text:
        text = text.replace("import secrets\n", "import secrets\nimport threading\n")
    if "from functools import wraps" not in text:
        text = text.replace("from enum import Enum\n", "from enum import Enum\nfrom functools import wraps\n")
    if "def _locked(method):" not in text:
        decorator = '''\n\ndef _locked(method):\n    @wraps(method)\n    def wrapper(self, *args, **kwargs):\n        with self._lock:\n            return method(self, *args, **kwargs)\n    return wrapper\n'''
        text = text.replace("\n\nclass RealtimeError", decorator + "\n\nclass RealtimeError")
    if "self._lock = threading.RLock()" not in text:
        text = text.replace("        self._consumed_ticket_ids: set[str] = set()\n", "        self._consumed_ticket_ids: set[str] = set()\n        self._lock = threading.RLock()\n")
    for method in ["issue_ticket", "activate", "transition", "interrupt", "revoke", "get"]:
        signature = f"    def {method}("
        if f"    @_locked\n{signature}" not in text:
            text = text.replace(signature, f"    @_locked\n{signature}", 1)
    path.write_text(text, encoding="utf-8")


def patch_capabilities() -> None:
    path = ROOT / "services/control_plane/capabilities.py"
    text = path.read_text(encoding="utf-8")
    if "import threading" not in text:
        text = text.replace("import json\n", "import json\nimport threading\n")
    text = text.replace("    def __init__(self) -> None:\n        self.entries: list[dict[str, Any]] = []\n", "    def __init__(self) -> None:\n        self.entries: list[dict[str, Any]] = []\n        self._lock = threading.RLock()\n")
    old_append = '''    def append(self, event: str, payload: Mapping[str, Any]) -> int:\n        previous = self.entries[-1]["hash"] if self.entries else ""\n        sequence = len(self.entries) + 1\n        body = {\n            "event": event,\n            "payload": dict(payload),\n            "previous_hash": previous,\n            "sequence": sequence,\n        }\n        body["hash"] = canonical_digest(body)\n        self.entries.append(body)\n        return sequence\n'''
    new_append = '''    def append(self, event: str, payload: Mapping[str, Any]) -> int:\n        with self._lock:\n            previous = self.entries[-1]["hash"] if self.entries else ""\n            sequence = len(self.entries) + 1\n            body = {\n                "event": event,\n                "payload": dict(payload),\n                "previous_hash": previous,\n                "sequence": sequence,\n            }\n            body["hash"] = canonical_digest(body)\n            self.entries.append(body)\n            return sequence\n'''
    if old_append in text:
        text = text.replace(old_append, new_append)
    if "self._state_lock = threading.RLock()" not in text:
        text = text.replace("        self._consumed_leases: set[str] = set()\n", "        self._consumed_leases: set[str] = set()\n        self._state_lock = threading.RLock()\n        self._idempotency_locks: dict[str, threading.Lock] = {}\n")
    old_register = '''    def register(\n        self, spec: CapabilitySpec, adapter: CapabilityAdapter\n    ) -> None:\n        if spec.name in self._specs:\n            raise CapabilityError("capability_already_registered")\n        self._specs[spec.name] = spec\n        self._adapters[spec.name] = adapter\n'''
    new_register = '''    def register(\n        self, spec: CapabilitySpec, adapter: CapabilityAdapter\n    ) -> None:\n        with self._state_lock:\n            if spec.name in self._specs:\n                raise CapabilityError("capability_already_registered")\n            self._specs[spec.name] = spec\n            self._adapters[spec.name] = adapter\n\n    def _lock_for(self, idempotency_key: str) -> threading.Lock:\n        if not idempotency_key:\n            raise CapabilityError("idempotency_key_required")\n        with self._state_lock:\n            return self._idempotency_locks.setdefault(idempotency_key, threading.Lock())\n'''
    if old_register in text:
        text = text.replace(old_register, new_register)
    signature = '''    def execute(\n        self,\n        request: CapabilityRequest,\n        *,\n        lease: DecisionLease | None = None,\n    ) -> CapabilityReceipt:\n'''
    if "def _execute_serialized(" not in text and signature in text:
        text = text.replace(signature, signature + "        lock = self._lock_for(request.idempotency_key)\n        with lock:\n            return self._execute_serialized(request, lease=lease)\n\n    def _execute_serialized(\n        self,\n        request: CapabilityRequest,\n        *,\n        lease: DecisionLease | None = None,\n    ) -> CapabilityReceipt:\n", 1)
    mutation = '''        if spec.mutating:\n            denial = self._validate_mutation(request, spec, lease, now)\n            if denial is not None:\n                return self._deny(request, denial)\n'''
    atomic = '''        if spec.mutating:\n            with self._state_lock:\n                denial = self._validate_mutation(request, spec, lease, now)\n                if denial is not None:\n                    return self._deny(request, denial)\n                if lease is not None and lease.single_use:\n                    self._consumed_leases.add(lease.lease_id)\n'''
    if mutation in text:
        text = text.replace(mutation, atomic)
        later = '''            if lease is not None and lease.single_use:\n                self._consumed_leases.add(lease.lease_id)\n'''
        first = text.find(later, text.find("decision_sequence ="))
        if first >= 0:
            text = text[:first] + text[first + len(later):]
    path.write_text(text, encoding="utf-8")


def patch_skills() -> None:
    path = ROOT / "services/skills/registry.py"
    text = path.read_text(encoding="utf-8")
    if "package_bytes: bytes" not in text:
        text = text.replace("        manifest: SkillManifest,\n        *,\n        consented_capabilities", "        manifest: SkillManifest,\n        *,\n        package_bytes: bytes,\n        consented_capabilities", 1)
        text = text.replace("    ) -> InstalledSkill:\n        self._validate_manifest(manifest)\n        manifest_version", "    ) -> InstalledSkill:\n        self._validate_manifest(manifest)\n        if not isinstance(package_bytes, bytes) or not package_bytes:\n            raise SkillError(\"skill_package_bytes_required\")\n        actual_package_digest = hashlib.sha256(package_bytes).hexdigest()\n        if not hmac.compare_digest(actual_package_digest, manifest.package_digest):\n            raise SkillError(\"skill_package_digest_mismatch\")\n        manifest_version", 1)
    text = text.replace("        if len(manifest.package_digest) != 64:\n            raise SkillError(\"skill_package_digest_invalid\")\n", "        if len(manifest.package_digest) != 64 or manifest.package_digest != manifest.package_digest.lower() or any(character not in \"0123456789abcdef\" for character in manifest.package_digest):\n            raise SkillError(\"skill_package_digest_invalid\")\n")
    path.write_text(text, encoding="utf-8")

    tests = ROOT / "services/skills/test_registry.py"
    source = tests.read_text(encoding="utf-8")
    if "PACKAGE_BYTES =" not in source:
        if "import hashlib" not in source:
            source = source.replace("from __future__ import annotations\n", "from __future__ import annotations\n\nimport hashlib\n", 1)
        index = min(value for value in [source.find("class "), source.find("def ")] if value >= 0)
        source = source[:index] + 'PACKAGE_BYTES = b"hepta-test-skill-package-v1"\nPACKAGE_DIGEST = hashlib.sha256(PACKAGE_BYTES).hexdigest()\n\n' + source[index:]
    source = re.sub(r'(["\'])[0-9a-f]\1\s*\*\s*64', 'PACKAGE_DIGEST', source)
    position = 0
    while True:
        start = source.find('.install(', position)
        if start < 0:
            break
        depth = 0
        quote = None
        escaped = False
        comma = None
        cursor = start + len('.install')
        while cursor < len(source):
            char = source[cursor]
            if quote is not None:
                if escaped:
                    escaped = False
                elif char == '\\':
                    escaped = True
                elif char == quote:
                    quote = None
            elif char in "'\"":
                quote = char
            elif char == '(':
                depth += 1
            elif char == ')':
                depth -= 1
                if depth == 0:
                    break
            elif char == ',' and depth == 1:
                comma = cursor
                break
            cursor += 1
        if comma is None:
            raise SystemExit('cannot parse SkillRegistry.install call')
        close = source.find(')', comma)
        if 'package_bytes=' not in source[start:close]:
            first_line = source[start:comma + 1].split('\n')[-1]
            indentation = re.match(r'\s*', first_line).group(0)
            source = source[:comma + 1] + f'\n{indentation}package_bytes=PACKAGE_BYTES,' + source[comma + 1:]
            position = comma + len(indentation) + 31
        else:
            position = comma + 1
    tests.write_text(source, encoding="utf-8")


def patch_model_gateway() -> None:
    path = ROOT / "services/model_gateway/app.py"
    text = path.read_text(encoding="utf-8")
    text = text.replace("MAX_CONTEXT_BYTES = 32 * 1024\n", 'MAX_CONTEXT_BYTES = 32 * 1024\nLOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})\n') if "LOOPBACK_HOSTS" not in text else text
    text = text.replace("def authorize(header_value: str | None, expected_token: str | None) -> bool:\n    if not expected_token:\n        return True\n", "def authorize(header_value: str | None, expected_token: str | None) -> bool:\n    if not expected_token:\n        return False\n")
    old = "    args = parser.parse_args()\n    server = ThreadingHTTPServer((args.host, args.port), GatewayHandler)\n"
    new = "    args = parser.parse_args()\n    if args.host not in LOOPBACK_HOSTS:\n        print(json.dumps({\"ok\": False, \"error\": \"development_gateway_loopback_only\"}, separators=(\",\", \":\")))\n        return 2\n    if not os.environ.get(\"HEPTA_GATEWAY_DEV_TOKEN\"):\n        print(json.dumps({\"ok\": False, \"error\": \"development_gateway_token_required\"}, separators=(\",\", \":\")))\n        return 2\n    server = ThreadingHTTPServer((args.host, args.port), GatewayHandler)\n"
    if old in text:
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")
    test = ROOT / "services/model_gateway/test_app.py"
    source = test.read_text(encoding="utf-8")
    source = re.sub(r'assertTrue\(authorize\(([^\n]*None[^\n]*)\)\)', r'assertFalse(authorize(\1))', source)
    source = re.sub(r'assert authorize\(([^\n]*None[^\n]*)\)', r'assert not authorize(\1)', source)
    test.write_text(source, encoding="utf-8")


def main() -> int:
    patch_realtime()
    patch_capabilities()
    patch_skills()
    patch_model_gateway()
    write("services/control_plane/test_realtime_concurrency.py", realtime_test_source())
    write("services/control_plane/test_capabilities_concurrency.py", capability_test_source())
    write("services/codex_worker/worker.py", worker_source())
    policy_path = ROOT / "services/codex_worker/policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["network_access_default"] = False
    policy["network_guard"] = ["unshare", "--net", "--"]
    policy_path.write_text(json.dumps(policy, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write("services/codex_worker/test_worker_isolation.py", worker_test_source())
    Path(__file__).unlink()
    workflow = ROOT / ".github/workflows/g7-services-materialize.yml"
    if workflow.exists():
        workflow.unlink()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
