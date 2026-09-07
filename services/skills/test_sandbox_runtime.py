from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from services.skills.sandbox_runtime import (
    LinuxBrokerOnlySandbox,
    SandboxLimits,
    SkillSandboxError,
)


class LinuxBrokerOnlySandboxTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = LinuxBrokerOnlySandbox()
        self.authority_calls = 0

    def authorize(self) -> None:
        self.authority_calls += 1

    def execute(self, source: str, *, input_value=None, allowed=(), handler=None,
                limits: SandboxLimits | None = None):
        return self.runtime.execute(
            source=source.encode("utf-8"),
            input_value={} if input_value is None else input_value,
            allowed_capabilities=allowed,
            capability_handler=handler or (lambda capability, arguments: {}),
            authorize=self.authorize,
            limits=limits or SandboxLimits(wall_seconds=3),
        )

    def assert_code(self, code: str, callback) -> None:
        with self.assertRaises(SkillSandboxError) as raised:
            callback()
        self.assertEqual(raised.exception.code, code)

    def test_arbitrary_python_executes_after_kernel_controls(self) -> None:
        result = self.execute(
            "import json,sys\n"
            "value=json.loads(sys.stdin.read())\n"
            "print(json.dumps({'echo':value},sort_keys=True,separators=(',',':')))\n",
            input_value={"value": 7},
        )
        self.assertEqual(result.output, {"echo": {"value": 7}})
        self.assertEqual(result.capability_requests, 0)
        self.assertEqual(len(result.stdout_digest), 64)
        self.assertGreaterEqual(self.authority_calls, 2)

    def test_direct_network_and_process_creation_are_denied_by_seccomp(self) -> None:
        result = self.execute(
            "import errno,json,os,socket\n"
            "codes={}\n"
            "try: socket.socket()\n"
            "except OSError as e: codes['socket']=e.errno\n"
            "try: os.fork()\n"
            "except OSError as e: codes['fork']=e.errno\n"
            "print(json.dumps(codes,sort_keys=True,separators=(',',':')))\n"
        )
        self.assertEqual(result.output, {"fork": 1, "socket": 1})

    def test_landlock_denies_filesystem_escape_but_allows_private_workspace(self) -> None:
        marker = "/tmp/hepta-skill-escape-must-not-exist"
        try:
            Path(marker).unlink()
        except FileNotFoundError:
            pass
        result = self.execute(
            "import json,os\n"
            "result={}\n"
            "try:\n"
            f" open({marker!r},'w').write('escape')\n"
            " result['escape']='allowed'\n"
            "except OSError as e: result['escape_errno']=e.errno\n"
            "open('inside','w').write('ok')\n"
            "result['inside']=open('inside').read()\n"
            "print(json.dumps(result,sort_keys=True,separators=(',',':')))\n"
        )
        self.assertEqual(result.output["inside"], "ok")
        self.assertIn(result.output["escape_errno"], {1, 13})
        self.assertFalse(Path(marker).exists())

    def test_preopened_capability_broker_is_the_only_effect_path(self) -> None:
        calls = []

        def handler(capability, arguments):
            calls.append((capability, dict(arguments)))
            return {"event_id": "calendar-event-a", "accepted": True}

        source = (
            "import json,os,struct\n"
            "fd=int(os.environ['HEPTA_CAPABILITY_FD'])\n"
            "request=json.dumps({'request_id':'request-a','capability':'calendar.create',"
            "'arguments':{'title':'meeting'}},sort_keys=True,separators=(',',':')).encode()\n"
            "os.write(fd,struct.pack('>I',len(request))+request)\n"
            "header=os.read(fd,4)\n"
            "size=struct.unpack('>I',header)[0]\n"
            "data=b''\n"
            "while len(data)<size: data+=os.read(fd,size-len(data))\n"
            "print(json.dumps(json.loads(data),sort_keys=True,separators=(',',':')))\n"
        )
        result = self.execute(
            source,
            allowed=("calendar.create",),
            handler=handler,
        )
        self.assertEqual(calls, [("calendar.create", {"title": "meeting"})])
        self.assertEqual(
            result.output,
            {
                "ok": True,
                "request_id": "request-a",
                "result": {"accepted": True, "event_id": "calendar-event-a"},
            },
        )
        self.assertEqual(result.capability_requests, 1)

    def test_unconsented_capability_is_denied_without_calling_handler(self) -> None:
        calls = []
        source = (
            "import json,os,struct\n"
            "fd=int(os.environ['HEPTA_CAPABILITY_FD'])\n"
            "request=json.dumps({'request_id':'request-a','capability':'calendar.write',"
            "'arguments':{}},sort_keys=True,separators=(',',':')).encode()\n"
            "os.write(fd,struct.pack('>I',len(request))+request)\n"
            "size=struct.unpack('>I',os.read(fd,4))[0]\n"
            "data=b''\n"
            "while len(data)<size: data+=os.read(fd,size-len(data))\n"
            "print(json.dumps(json.loads(data),sort_keys=True,separators=(',',':')))\n"
        )
        result = self.execute(
            source,
            allowed=(),
            handler=lambda capability, arguments: calls.append(capability) or {},
        )
        self.assertEqual(calls, [])
        self.assertEqual(
            result.output,
            {
                "error": "capability_denied",
                "ok": False,
                "request_id": "request-a",
            },
        )

    def test_running_task_is_terminated_when_authority_is_revoked(self) -> None:
        calls = 0

        def authority() -> None:
            nonlocal calls
            calls += 1
            if calls >= 4:
                raise RuntimeError("revoked")

        self.assert_code(
            "skill_authority_revoked",
            lambda: self.runtime.execute(
                source=(
                    "import time\n"
                    "while True: time.sleep(.05)\n"
                ).encode(),
                input_value={},
                allowed_capabilities=(),
                capability_handler=lambda capability, arguments: {},
                authorize=authority,
                limits=SandboxLimits(wall_seconds=3),
            ),
        )
        self.assertGreaterEqual(calls, 4)

    def test_timeout_and_output_limits_are_enforced(self) -> None:
        self.assert_code(
            "skill_timeout",
            lambda: self.execute(
                "import time\ntime.sleep(5)\n",
                limits=SandboxLimits(wall_seconds=.1, cpu_seconds=2),
            ),
        )
        self.assert_code(
            "skill_output_exceeded",
            lambda: self.execute(
                "print('x'*100000)\n",
                limits=SandboxLimits(wall_seconds=2, output_bytes=128),
            ),
        )

    def test_file_size_limit_is_explicit_and_validated(self) -> None:
        self.assert_code(
            "skill_sandbox_limits_invalid",
            lambda: SandboxLimits(file_size_bytes=0),
        )
        self.assert_code(
            "skill_sandbox_limits_invalid",
            lambda: SandboxLimits(file_size_bytes=64 * 1024 * 1024 + 1),
        )

    def test_stderr_and_runtime_exception_do_not_leak_detail(self) -> None:
        self.assert_code(
            "skill_stderr_forbidden",
            lambda: self.execute(
                "import json,sys\n"
                "sys.stderr.write('attacker detail')\n"
                "print(json.dumps({'ok':True}))\n"
            ),
        )
        self.assert_code(
            "skill_runtime_failed",
            lambda: self.execute(
                "raise RuntimeError('SECRET-ATTACKER-DETAIL')\n"
            ),
        )

    def test_invalid_source_input_and_broker_frames_fail_closed(self) -> None:
        self.assert_code(
            "skill_source_invalid",
            lambda: self.runtime.execute(
                source=b"\xff",
                input_value={},
                allowed_capabilities=(),
                capability_handler=lambda capability, arguments: {},
                authorize=self.authorize,
            ),
        )
        self.assert_code(
            "skill_input_invalid",
            lambda: self.runtime.execute(
                source=b"print('{}')\n",
                input_value={"bad": object()},
                allowed_capabilities=(),
                capability_handler=lambda capability, arguments: {},
                authorize=self.authorize,
            ),
        )
        self.assert_code(
            "skill_broker_frame_invalid",
            lambda: self.execute(
                "import os,struct,time\n"
                "fd=int(os.environ['HEPTA_CAPABILITY_FD'])\n"
                "os.write(fd,struct.pack('>I',70000))\n"
                "time.sleep(.5)\n"
            ),
        )


if __name__ == "__main__":
    unittest.main()
