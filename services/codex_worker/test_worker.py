from __future__ import annotations

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
        self.assertEqual(command[0:3], ["codex", "exec", "--ephemeral"])
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
        env = bounded_environment({"PATH": "/bin", "SECRET": "hidden"})
        self.assertEqual(env, {"PATH": "/bin"})

    def test_output_file_is_outside_workspace(self) -> None:
        task = validate_task(
            self.task(), workspace_root=self.root, policy=self.policy
        )
        output = self.root.parent / "result.txt"
        command = build_command(task, policy=self.policy, output_path=output)
        self.assertEqual(command[-2], str(output))


if __name__ == "__main__":
    unittest.main()
