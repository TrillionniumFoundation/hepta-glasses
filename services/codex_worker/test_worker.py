from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

from services.codex_worker.worker import (
    WorkerError,
    WorkerPolicy,
    bounded_environment,
    build_command,
    run_task,
    validate_task,
)


class CodexWorkerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = WorkerPolicy.load()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "repo").mkdir()

    def task(self, **updates: object) -> dict[str, object]:
        value: dict[str, object] = {
            "task_id": "task-1",
            "prompt": "Inspect the repository and report only verified findings.",
            "workspace": "repo",
            "sandbox": "read-only",
            "timeout_seconds": 60,
        }
        value.update(updates)
        return value

    def test_builds_fixed_noninteractive_command(self) -> None:
        task = validate_task(
            self.task(), workspace_root=self.root, policy=self.policy
        )
        result = run_task(task, policy=self.policy, dry_run=True)
        command = result["command"]
        self.assertEqual(
            command[: len(self.policy.network_isolation_command)],
            list(self.policy.network_isolation_command),
        )
        self.assertIn("codex", command)
        self.assertIn("--ephemeral", command)
        self.assertIn("--json", command)
        self.assertEqual(command[-1], "-")

    def test_rejects_workspace_escape(self) -> None:
        outside = self.root.parent
        with self.assertRaises(WorkerError) as raised:
            validate_task(
                self.task(workspace=str(outside)),
                workspace_root=self.root,
                policy=self.policy,
            )
        self.assertEqual(raised.exception.code, "workspace_outside_root")

    def test_rejects_unapproved_sandbox(self) -> None:
        with self.assertRaises(WorkerError) as raised:
            validate_task(
                self.task(sandbox="unbounded"),
                workspace_root=self.root,
                policy=self.policy,
            )
        self.assertEqual(raised.exception.code, "sandbox_not_allowed")

    def test_environment_is_allowlisted(self) -> None:
        env = bounded_environment(
            {
                "PATH": "/bin",
                "CODEX_HOME": "/persistent/codex",
                "SECRET": "hidden",
            }
        )
        self.assertEqual(env, {"PATH": "/bin"})

    def test_workspace_symlink_escape_is_rejected(self) -> None:
        outside = self.root.parent / "outside.txt"
        outside.write_text("secret", encoding="utf-8")
        os.symlink(outside, self.root / "repo" / "escape")
        with self.assertRaises(WorkerError) as raised:
            validate_task(
                self.task(),
                workspace_root=self.root,
                policy=self.policy,
            )
        self.assertEqual(raised.exception.code, "workspace_symlink_escape")

    def test_workspace_symlink_to_sibling_workspace_is_rejected(self) -> None:
        sibling = self.root / "sibling"
        sibling.mkdir()
        target = sibling / "data.txt"
        target.write_text("sibling", encoding="utf-8")
        os.symlink(target, self.root / "repo" / "sibling-link")
        with self.assertRaises(WorkerError) as raised:
            validate_task(
                self.task(),
                workspace_root=self.root,
                policy=self.policy,
            )
        self.assertEqual(raised.exception.code, "workspace_symlink_escape")

    def test_streaming_output_limit_terminates_worker(self) -> None:
        script = self.root / "emit.py"
        script.write_text(
            "#!/usr/bin/env python3\nprint('x' * 4096)\n",
            encoding="utf-8",
        )
        script.chmod(0o755)
        policy = WorkerPolicy(
            allowed_sandboxes=("read-only",),
            maximum_prompt_characters=24_000,
            maximum_timeout_seconds=10,
            maximum_output_bytes=128,
            maximum_workspace_entries=100,
            executable=str(script),
            network_access_default=True,
            network_isolation_command=(),
        )
        task = validate_task(
            self.task(timeout_seconds=5),
            workspace_root=self.root,
            policy=policy,
        )
        with self.assertRaises(WorkerError) as raised:
            run_task(task, policy=policy)
        self.assertEqual(raised.exception.code, "codex_output_too_large")

    def test_result_redacts_token_shaped_material(self) -> None:
        script = self.root / "emit-secret.py"
        script.write_text(
            "#!/usr/bin/env python3\n"
            "print('ghp_' + 'a' * 40)\n",
            encoding="utf-8",
        )
        script.chmod(0o755)
        policy = WorkerPolicy(
            allowed_sandboxes=("read-only",),
            maximum_prompt_characters=24_000,
            maximum_timeout_seconds=10,
            maximum_output_bytes=4096,
            maximum_workspace_entries=100,
            executable=str(script),
            network_access_default=True,
            network_isolation_command=(),
        )
        task = validate_task(
            self.task(timeout_seconds=5),
            workspace_root=self.root,
            policy=policy,
        )
        result = run_task(task, policy=policy)
        self.assertEqual(result["event_stream"].strip(), "[REDACTED]")

    def test_output_file_is_outside_workspace(self) -> None:
        task = validate_task(
            self.task(), workspace_root=self.root, policy=self.policy
        )
        output = self.root.parent / "result.txt"
        command = build_command(task, policy=self.policy, output_path=output)
        self.assertEqual(command[-2], str(output))


if __name__ == "__main__":
    unittest.main()
