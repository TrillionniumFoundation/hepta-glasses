from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
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

    def executable_script(self, name: str, body: str) -> Path:
        path = self.root / name
        path.write_text("#!/usr/bin/env python3\n" + body, encoding="utf-8")
        path.chmod(0o700)
        return path

    def passthrough_wrapper(self) -> Path:
        return self.executable_script(
            "isolate-test",
            "import os\n"
            "import sys\n"
            "os.execv(sys.argv[1], sys.argv[1:])\n",
        )

    def execution_policy(
        self,
        executable: Path,
        *,
        maximum_output_bytes: int = 4096,
    ) -> WorkerPolicy:
        return WorkerPolicy(
            allowed_sandboxes=("read-only",),
            maximum_prompt_characters=24_000,
            maximum_timeout_seconds=60,
            maximum_output_bytes=maximum_output_bytes,
            executable=str(executable),
            network_isolation_command=(str(self.passthrough_wrapper()),),
            require_network_isolation=True,
        )

    def validated_task(self, policy: WorkerPolicy):
        return validate_task(
            self.task(),
            workspace_root=self.root,
            policy=policy,
        )

    def test_builds_fixed_noninteractive_network_isolated_command(self) -> None:
        task = validate_task(
            self.task(), workspace_root=self.root, policy=self.policy
        )
        result = run_task(task, policy=self.policy, dry_run=True)
        command = result["command"]
        self.assertEqual(command[0:3], ["unshare", "--net", "--"])
        self.assertEqual(command[3:6], ["codex", "exec", "--ephemeral"])
        self.assertIn("--json", command)
        self.assertEqual(command[-1], "-")
        self.assertTrue(result["network_isolated"])
        self.assertFalse(result["host_home_inherited"])

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

    def test_environment_uses_ephemeral_homes_and_drops_host_secrets(self) -> None:
        home = self.root / "home"
        codex_home = self.root / "codex-home"
        env = bounded_environment(
            {
                "PATH": "/bin",
                "HOME": "/host/home",
                "CODEX_HOME": "/host/codex",
                "SECRET": "hidden",
            },
            home=home,
            codex_home=codex_home,
        )
        self.assertEqual(
            env,
            {
                "PATH": "/bin",
                "HOME": str(home),
                "CODEX_HOME": str(codex_home),
            },
        )

    def test_output_file_is_outside_workspace(self) -> None:
        task = validate_task(
            self.task(), workspace_root=self.root, policy=self.policy
        )
        output = self.root.parent / "result.txt"
        command = build_command(task, policy=self.policy, output_path=output)
        self.assertEqual(command[-2], str(output))
        self.assertNotIn(str(output), str(task.workspace))

    def test_missing_network_isolation_configuration_fails_closed(self) -> None:
        policy = replace(self.policy, network_isolation_command=())
        task = validate_task(
            self.task(), workspace_root=self.root, policy=policy
        )
        with self.assertRaises(WorkerError) as raised:
            build_command(
                task,
                policy=policy,
                output_path=self.root / "result.txt",
            )
        self.assertEqual(raised.exception.code, "network_isolation_required")

    def test_streaming_output_limit_kills_oversized_child(self) -> None:
        executable = self.executable_script(
            "fake-codex-large",
            "import sys\n"
            "sys.stdout.buffer.write(b'x' * 8192)\n"
            "sys.stdout.buffer.flush()\n",
        )
        policy = self.execution_policy(executable, maximum_output_bytes=256)
        with self.assertRaises(WorkerError) as raised:
            run_task(self.validated_task(policy), policy=policy)
        self.assertEqual(raised.exception.code, "codex_output_too_large")

    def test_last_message_is_included_in_total_output_budget(self) -> None:
        executable = self.executable_script(
            "fake-codex-last-message-large",
            "import pathlib\n"
            "import sys\n"
            "output = pathlib.Path(sys.argv[sys.argv.index('--output-last-message') + 1])\n"
            "output.write_bytes(b'y' * 1024)\n",
        )
        policy = self.execution_policy(executable, maximum_output_bytes=128)
        with self.assertRaises(WorkerError) as raised:
            run_task(self.validated_task(policy), policy=policy)
        self.assertEqual(raised.exception.code, "codex_output_too_large")

    def test_last_message_symlink_is_rejected(self) -> None:
        executable = self.executable_script(
            "fake-codex-last-message-link",
            "import os\n"
            "import sys\n"
            "output = sys.argv[sys.argv.index('--output-last-message') + 1]\n"
            "os.symlink('/etc/hosts', output)\n",
        )
        policy = self.execution_policy(executable)
        with self.assertRaises(WorkerError) as raised:
            run_task(self.validated_task(policy), policy=policy)
        self.assertEqual(raised.exception.code, "codex_last_message_invalid")

    def test_child_observes_only_worker_owned_home_directories(self) -> None:
        executable = self.executable_script(
            "fake-codex-environment",
            "import json\n"
            "import os\n"
            "import pathlib\n"
            "import sys\n"
            "output = pathlib.Path(sys.argv[sys.argv.index('--output-last-message') + 1])\n"
            "output.write_text(json.dumps({'HOME': os.environ.get('HOME'), 'CODEX_HOME': os.environ.get('CODEX_HOME')}))\n",
        )
        policy = self.execution_policy(executable)
        result = run_task(self.validated_task(policy), policy=policy)
        environment = json.loads(result["last_message"])
        self.assertIn("hepta-codex-task-1-", environment["HOME"])
        self.assertIn("hepta-codex-task-1-", environment["CODEX_HOME"])
        self.assertNotEqual(environment["HOME"], str(Path.home()))


if __name__ == "__main__":
    unittest.main()
