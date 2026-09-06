from __future__ import annotations

import os
import tempfile
import threading
import subprocess
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from services.codex_worker.task_supervisor import (
    SupervisedTask,
    SupervisorError,
    TaskLimits,
    run_supervised,
)


class TaskSupervisorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def script(self, name: str, body: str) -> Path:
        path = self.root / name
        path.write_text("#!/usr/bin/env python3\n" + body, encoding="utf-8")
        path.chmod(0o700)
        return path

    def task(self, path: Path, *args: str, **updates: object) -> SupervisedTask:
        values = dict(
            executable=str(path), arguments=tuple(args), working_directory=str(self.root),
            limits=TaskLimits(wall_seconds=2, cpu_seconds=1, address_space_bytes=256*1024*1024,
                              file_size_bytes=1024*1024, open_files=32, processes=8,
                              output_bytes=65536),
        )
        values.update(updates)
        return SupervisedTask(**values)

    def error(self, code: str, callback) -> None:
        with self.assertRaises(SupervisorError) as raised:
            callback()
        self.assertEqual(raised.exception.code, code)

    def test_success_uses_sanitized_environment_and_input(self) -> None:
        script = self.script("ok.py", "import os,sys\nprint(os.getenv('ALLOWED'))\nprint(os.getenv('SECRET'))\nprint(sys.stdin.buffer.read().decode())\n")
        result = run_supervised(self.task(script, environment={"ALLOWED":"yes"}, input_bytes=b"input"))
        self.assertEqual(result.return_code, 0)
        self.assertEqual(result.stderr, b"")
        self.assertEqual(result.stdout.splitlines(), [b"yes", b"None", b"input"])

    def test_relative_and_symlink_executables_fail_closed(self) -> None:
        script = self.script("real.py", "print('ok')\n")
        self.error("task_executable_invalid", lambda: SupervisedTask(executable="real.py"))
        link = self.root / "link.py"; link.symlink_to(script)
        self.error("task_executable_linked", lambda: run_supervised(self.task(link)))

    def test_working_directory_symlink_is_rejected(self) -> None:
        script = self.script("noop-dir.py", "pass\n")
        real = self.root / "real-work"; real.mkdir()
        link = self.root / "linked-work"; link.symlink_to(real, target_is_directory=True)
        self.error("task_working_directory_linked",
                   lambda: run_supervised(self.task(script, working_directory=str(link))))

    def test_working_directory_replacement_during_spawn_fails_closed(self) -> None:
        script = self.script("delayed.py", "import time\ntime.sleep(.3)\nopen('ran','w').write('x')\n")
        workspace = self.root / "workspace"; workspace.mkdir()
        detached = self.root / "detached"
        original = subprocess.Popen
        def replace_then_spawn(*args, **kwargs):
            workspace.rename(detached)
            workspace.mkdir()
            return original(*args, **kwargs)
        with patch("services.codex_worker.task_supervisor.subprocess.Popen", side_effect=replace_then_spawn):
            self.error("task_working_directory_replaced",
                       lambda: run_supervised(self.task(script, working_directory=str(workspace))))
        time.sleep(.5)
        self.assertFalse((workspace / "ran").exists())
        self.assertFalse((detached / "ran").exists())

    def test_group_writable_and_hardlinked_executables_are_rejected(self) -> None:
        script = self.script("bad.py", "print('ok')\n")
        script.chmod(0o720)
        self.error("task_executable_permissions_invalid", lambda: run_supervised(self.task(script)))
        script.chmod(0o700)
        alias = self.root / "alias.py"; os.link(script, alias)
        self.error("task_executable_permissions_invalid", lambda: run_supervised(self.task(script)))

    def test_argument_is_not_interpreted_by_a_shell(self) -> None:
        marker = self.root / "marker"
        script = self.script("args.py", "import sys\nprint(sys.argv[1])\n")
        payload = f"x; touch {marker}"
        result = run_supervised(self.task(script, payload))
        self.assertIn(payload.encode(), result.stdout)
        self.assertFalse(marker.exists())

    def test_timeout_kills_entire_process_group(self) -> None:
        marker = self.root / "late"
        script = self.script("fork.py", f"import os,time\nif os.fork()==0:\n time.sleep(.4); open({str(marker)!r},'w').write('late'); os._exit(0)\ntime.sleep(5)\n")
        limits = TaskLimits(wall_seconds=.1, cpu_seconds=2, address_space_bytes=256*1024*1024,
                            file_size_bytes=1024*1024, open_files=32, processes=8, output_bytes=1024)
        self.error("task_timeout", lambda: run_supervised(self.task(script, limits=limits)))
        time.sleep(.6)
        self.assertFalse(marker.exists())

    def test_timeout_kills_descendant_after_group_leader_exits(self) -> None:
        marker = self.root / "orphan-late"
        script = self.script("orphan.py", f"import os,time\nif os.fork()==0:\n time.sleep(.5); open({str(marker)!r},'w').write('late'); os._exit(0)\nos._exit(0)\n")
        limits = TaskLimits(wall_seconds=.1, cpu_seconds=2, address_space_bytes=256*1024*1024,
                            file_size_bytes=1024*1024, open_files=32, processes=8, output_bytes=1024)
        self.error("task_timeout", lambda: run_supervised(self.task(script, limits=limits)))
        time.sleep(.7)
        self.assertFalse(marker.exists())

    def test_successful_leader_cannot_leave_pipe_detached_descendant(self) -> None:
        marker = self.root / "detached-late"
        interpreter = Path("/usr/bin/python3").resolve(strict=True)
        code = f"import os,time\nif os.fork()==0:\n fd=os.open('/dev/null',os.O_RDWR); [os.dup2(fd,n) for n in (0,1,2)]; fd>2 and os.close(fd); time.sleep(.4); open({str(marker)!r},'w').write('late'); os._exit(0)\nos._exit(0)\n"
        result = run_supervised(self.task(interpreter, "-I", "-c", code))
        self.assertEqual(result.return_code, 0)
        time.sleep(.6)
        self.assertFalse(marker.exists())

    def test_cancellation_kills_entire_process_group(self) -> None:
        marker = self.root / "late-cancel"
        script = self.script("cancel.py", f"import os,time\nif os.fork()==0:\n time.sleep(.5); open({str(marker)!r},'w').write('late'); os._exit(0)\ntime.sleep(5)\n")
        cancel = threading.Event()
        timer = threading.Timer(.1, cancel.set); timer.start(); self.addCleanup(timer.cancel)
        self.error("task_cancelled", lambda: run_supervised(self.task(script), cancel=cancel))
        time.sleep(.7)
        self.assertFalse(marker.exists())

    def test_output_limit_kills_process(self) -> None:
        script = self.script("output.py", "import sys,time\nsys.stdout.write('x'*100000); sys.stdout.flush(); time.sleep(5)\n")
        limits = TaskLimits(wall_seconds=2, cpu_seconds=1, address_space_bytes=256*1024*1024,
                            file_size_bytes=1024*1024, open_files=32, processes=8, output_bytes=128)
        self.error("task_output_exceeded", lambda: run_supervised(self.task(script, limits=limits)))

    def test_file_size_limit_is_applied_before_target_exec(self) -> None:
        output = self.root / "large"
        script = self.script("file.py", f"open({str(output)!r},'wb').write(b'x'*65536)\n")
        limits = TaskLimits(wall_seconds=2, cpu_seconds=1, address_space_bytes=256*1024*1024,
                            file_size_bytes=1024, open_files=32, processes=8, output_bytes=4096)
        result = run_supervised(self.task(script, limits=limits))
        self.assertNotEqual(result.return_code, 0)
        self.assertLessEqual(output.stat().st_size, 1024)

    def test_pre_cancelled_task_never_executes(self) -> None:
        marker = self.root / "started"
        script = self.script("never.py", f"open({str(marker)!r},'w').write('x')\n")
        cancel = threading.Event(); cancel.set()
        self.error("task_cancelled", lambda: run_supervised(self.task(script), cancel=cancel))
        self.assertFalse(marker.exists())

    def test_invalid_limits_and_environment_are_rejected(self) -> None:
        self.error("task_cpu_limit_invalid", lambda: TaskLimits(cpu_seconds=True))
        script = self.script("noop.py", "pass\n")
        self.error("task_environment_invalid", lambda: self.task(script, environment={"bad-name":"x"}))
        self.error("task_environment_invalid", lambda: self.task(script, environment={"HOME":"/tmp/escape"}))
        self.error("task_input_invalid", lambda: self.task(script, input_bytes=b"x"*32769))


if __name__ == "__main__":
    unittest.main()
