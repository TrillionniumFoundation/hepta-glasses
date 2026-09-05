from __future__ import annotations

import json
import threading
import unittest
from pathlib import Path

from services.skills.data_vm import (
    DataSkillInvocation,
    DataSkillResult,
    DataSkillRuntime,
)
from services.skills.signed_package import SignedSkillError, canonical, sha256
from services.skills.signed_registry import CheckedSkill, SignedSkillRegistry


class Registry(SignedSkillRegistry):
    def __init__(self, checked: CheckedSkill):
        self.checked = checked
        self.calls = 0
        self.second = None
        self.second_error = None

    def resolve(self, skill_id, *, package):
        self.calls += 1
        if skill_id != "pure" or package != b"package":
            raise SignedSkillError("fixture_binding")
        if self.calls >= 2 and self.second_error:
            raise SignedSkillError(self.second_error)
        return self.second if self.calls >= 2 and self.second is not None else self.checked


def program(steps=None, result="output"):
    return canonical({
        "schema_version": 1,
        "steps": steps or [
            {"id": "name", "op": "input", "path": ["name"]},
            {"id": "prefix", "op": "literal", "value": "Hello "},
            {"id": "output", "op": "concat", "items": ["prefix", "name"]},
        ],
        "result": result,
    })


def checked(raw=None, **manifest_changes):
    raw = raw or program()
    manifest = {
        "schema_version": 1,
        "skill_id": "pure",
        "version": "1.0.0",
        "publisher": "publisher",
        "key_id": "publisher-v1",
        "entrypoint": "program.json",
        "capabilities": [],
        "data_classes": ["personal", "public"],
        "network_domains": [],
        "risk_tier": "R0",
        "timeout_ms": 1000,
        "issued_at": 1000,
        "expires_at": 1500,
        "package_sha256": "0" * 64,
        "files": [],
        "dependencies": [],
    }
    manifest.update(manifest_changes)
    return CheckedSkill(canonical(manifest), (("program.json", raw), ("ignored.py", b"raise SystemExit")), 1400, 7)


class DataSkillRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.registry = Registry(checked())
        self.runtime = DataSkillRuntime(self.registry, monotonic=lambda: 0.0)
        self.invocation = DataSkillInvocation({"name": "Ada"}, frozenset({"personal"}))

    def error(self, code, callback):
        with self.assertRaises(SignedSkillError) as caught:
            callback()
        self.assertEqual(caught.exception.code, code)

    def execute(self, **changes):
        args = dict(skill_id="pure", package=b"package", invocation=self.invocation,
                    timeout_seconds=1)
        args.update(changes)
        return self.runtime.execute(**args)

    def test_pure_program_executes_and_returns_immutable_canonical_result(self):
        result = self.execute()
        self.assertIsInstance(result, DataSkillResult)
        self.assertEqual(result.output, "Hello Ada")
        self.assertEqual(result.output_json, b'"Hello Ada"')
        self.assertEqual(result.output_sha256, sha256(result.output_json))
        self.assertEqual(result.event_sequence, 7)
        self.assertEqual(result.instruction_count, 3)
        self.assertEqual(self.registry.calls, 2)

    def test_object_array_select_equal_slice_and_length(self):
        raw = program([
            {"id": "items", "op": "input", "path": ["items"]},
            {"id": "first", "op": "slice", "value": "items", "start": 0, "end": 1},
            {"id": "one", "op": "literal", "value": 1},
            {"id": "count", "op": "length", "value": "items"},
            {"id": "is_one", "op": "equal", "left": "count", "right": "one"},
            {"id": "yes", "op": "literal", "value": "yes"},
            {"id": "no", "op": "literal", "value": "no"},
            {"id": "label", "op": "select", "condition": "is_one", "when_true": "yes", "when_false": "no"},
            {"id": "array", "op": "array", "items": ["first", "label"]},
            {"id": "output", "op": "object", "fields": {"result": "array"}},
        ])
        self.registry.checked = checked(raw)
        result = self.execute(invocation=DataSkillInvocation({"items": ["x"]}, frozenset({"public"})))
        self.assertEqual(result.output, {"result": [["x"], "yes"]})

    def test_package_python_is_never_executed_or_imported(self):
        result = self.execute()
        self.assertEqual(result.output, "Hello Ada")
        self.assertEqual(self.registry.checked.files[1][1], b"raise SystemExit")

    def test_runtime_source_has_no_network_process_dynamic_execution_or_file_open(self):
        source = Path(__file__).with_name("data_vm.py").read_text()
        for marker in ("import socket", "import subprocess", "import os", "eval(", "exec(",
                       "__import__", "importlib", "open("):
            self.assertNotIn(marker, source)

    def test_requires_real_registry_type_and_trusted_monotonic_callable(self):
        self.error("skill_vm_configuration_invalid", lambda: DataSkillRuntime(object()))
        self.error("skill_vm_configuration_invalid", lambda: DataSkillRuntime(self.registry, monotonic=3))

    def test_only_r0_zero_capability_zero_domain_manifests_run(self):
        for changes in ({"risk_tier": "R1"}, {"capabilities": ["memory.read"]},
                        {"network_domains": ["service.example"]}):
            with self.subTest(changes=changes):
                self.registry = Registry(checked(**changes))
                runtime = DataSkillRuntime(self.registry, monotonic=lambda: 0.0)
                self.error("skill_vm_policy_not_pure", lambda: runtime.execute(
                    skill_id="pure", package=b"package", invocation=self.invocation))

    def test_declared_data_classes_bound_each_invocation(self):
        self.error("skill_vm_data_class_not_declared", lambda: self.execute(
            invocation=DataSkillInvocation({"name": "Ada"}, frozenset({"sensitive"}))))
        self.error("skill_vm_invocation_invalid", lambda: self.execute(
            invocation=DataSkillInvocation({"name": "Ada"}, frozenset({"credential"}))))

    def test_entrypoint_must_be_one_exact_json_member(self):
        for changes in ({"entrypoint": "main.py"}, {"entrypoint": "missing.json"}):
            self.registry = Registry(checked(**changes))
            runtime = DataSkillRuntime(self.registry, monotonic=lambda: 0.0)
            self.error("skill_vm_entrypoint_invalid", lambda: runtime.execute(
                skill_id="pure", package=b"package", invocation=self.invocation))
        duplicate = checked()
        duplicate = CheckedSkill(duplicate.document,
            (("program.json", program()), ("program.json", program())), 1400, 7)
        self.registry = Registry(duplicate)
        self.error("skill_vm_entrypoint_invalid", lambda: DataSkillRuntime(
            self.registry, monotonic=lambda: 0.0).execute(
                skill_id="pure", package=b"package", invocation=self.invocation))

    def test_noncanonical_duplicate_and_extra_program_fields_rejected(self):
        raws = [
            program() + b" ",
            b'{"result":"output","result":"output","schema_version":1,"steps":[]}',
            canonical({"schema_version": 1, "steps": [], "result": "x", "extra": True}),
        ]
        for raw in raws:
            with self.subTest(raw=raw[:30]):
                registry = Registry(checked(raw))
                runtime = DataSkillRuntime(registry, monotonic=lambda: 0.0)
                with self.assertRaises(SignedSkillError):
                    runtime.execute(skill_id="pure", package=b"package", invocation=self.invocation)

    def test_unknown_opcode_and_extra_instruction_fields_rejected(self):
        for steps, code in (
            ([{"id": "output", "op": "network", "target": "example.invalid"}], "skill_vm_opcode_forbidden"),
            ([{"id": "output", "op": "literal", "value": 1, "extra": 2}], "skill_vm_instruction_invalid"),
        ):
            registry = Registry(checked(program(steps)))
            runtime = DataSkillRuntime(registry, monotonic=lambda: 0.0)
            self.error(code, lambda r=runtime: r.execute(
                skill_id="pure", package=b"package", invocation=self.invocation))

    def test_forward_missing_and_duplicate_references_rejected(self):
        cases = [
            program([{"id": "output", "op": "lower", "value": "later"},
                     {"id": "later", "op": "literal", "value": "x"}]),
            program([{"id": "x", "op": "literal", "value": 1},
                     {"id": "x", "op": "literal", "value": 2}], result="x"),
            program([{"id": "x", "op": "literal", "value": 1}], result="missing"),
        ]
        for raw in cases:
            registry = Registry(checked(raw))
            runtime = DataSkillRuntime(registry, monotonic=lambda: 0.0)
            with self.assertRaises(SignedSkillError):
                runtime.execute(skill_id="pure", package=b"package", invocation=self.invocation)

    def test_input_path_is_plain_dict_list_navigation_only(self):
        raw = program([{"id": "output", "op": "input", "path": ["a", 1, "b"]}])
        registry = Registry(checked(raw))
        runtime = DataSkillRuntime(registry, monotonic=lambda: 0.0)
        result = runtime.execute(skill_id="pure", package=b"package",
            invocation=DataSkillInvocation({"a": [0, {"b": "ok"}]}, frozenset({"public"})))
        self.assertEqual(result.output, "ok")
        self.error("skill_vm_input_path_missing", lambda: runtime.execute(
            skill_id="pure", package=b"package",
            invocation=DataSkillInvocation({"a": []}, frozenset({"public"}))))

    def test_custom_types_float_large_integer_and_surrogate_input_rejected(self):
        class Custom(dict):
            pass
        for value in (Custom(name="Ada"), {"name": 1.5}, {"name": 1 << 54},
                      {"name": "\ud800"}, {"name": object()}):
            with self.subTest(value=repr(value)):
                self.error("skill_vm_input_invalid", lambda v=value: self.execute(
                    invocation=DataSkillInvocation(v, frozenset({"personal"}))))

    def test_input_is_defensively_snapshotted_before_execution(self):
        original = {"name": "Ada"}
        calls = [0]
        def clock():
            calls[0] += 1
            if calls[0] == 1:
                original["name"] = "changed"
            return 0.0
        runtime = DataSkillRuntime(self.registry, monotonic=clock)
        result = runtime.execute(skill_id="pure", package=b"package",
            invocation=DataSkillInvocation(original, frozenset({"personal"})))
        self.assertEqual(result.output, "Hello Ada")
        self.assertEqual(original["name"], "changed")

    def test_each_value_and_total_working_set_are_bounded(self):
        huge = "x" * 65000
        steps = [{"id": f"v{i}", "op": "input", "path": ["value"]} for i in range(5)]
        registry = Registry(checked(program(steps, result="v4")))
        runtime = DataSkillRuntime(registry, monotonic=lambda: 0.0)
        self.error("skill_vm_working_set_exhausted", lambda: runtime.execute(
            skill_id="pure", package=b"package",
            invocation=DataSkillInvocation({"value": huge}, frozenset({"public"}))))
        self.error("skill_vm_input_invalid", lambda: self.execute(
            invocation=DataSkillInvocation({"name": "x" * 70000}, frozenset({"personal"}))))

    def test_cancel_before_start_and_during_steps(self):
        event = threading.Event(); event.set()
        self.error("skill_vm_cancelled", lambda: self.execute(cancel=event))
        event.clear(); calls = [0]
        def clock():
            calls[0] += 1
            if calls[0] == 3:
                event.set()
            return 0.0
        runtime = DataSkillRuntime(self.registry, monotonic=clock)
        self.error("skill_vm_cancelled", lambda: runtime.execute(
            skill_id="pure", package=b"package", invocation=self.invocation, cancel=event))

    def test_deadline_and_invalid_clock_fail_closed(self):
        values = iter([0.0, 0.0, 2.0])
        runtime = DataSkillRuntime(self.registry, monotonic=lambda: next(values))
        self.error("skill_vm_deadline_expired", lambda: runtime.execute(
            skill_id="pure", package=b"package", invocation=self.invocation,
            timeout_seconds=1))
        for value in (True, float("nan"), float("inf"), "0"):
            runtime = DataSkillRuntime(self.registry, monotonic=lambda v=value: v)
            self.error("skill_vm_clock_invalid", lambda r=runtime: r.execute(
                skill_id="pure", package=b"package", invocation=self.invocation))

    def test_manifest_timeout_caps_caller_timeout(self):
        registry = Registry(checked(timeout_ms=10))
        values = iter([0.0, 0.0, 0.02])
        runtime = DataSkillRuntime(registry, monotonic=lambda: next(values))
        self.error("skill_vm_deadline_expired", lambda: runtime.execute(
            skill_id="pure", package=b"package", invocation=self.invocation,
            timeout_seconds=10))

    def test_final_registry_revocation_or_snapshot_change_withholds_output(self):
        self.registry.second_error = "skill_revoked"
        self.error("skill_revoked", self.execute)
        self.registry.calls = 0; self.registry.second_error = None
        changed = checked(); changed = CheckedSkill(changed.document, changed.files, 1400, 8)
        self.registry.second = changed
        self.error("skill_vm_admission_changed", self.execute)

    def test_output_property_returns_a_defensive_copy(self):
        raw = program([
            {"id": "value", "op": "literal", "value": [1]},
            {"id": "output", "op": "object", "fields": {"items": "value"}},
        ])
        self.registry.checked = checked(raw)
        result = self.execute()
        first = result.output; first["items"].append(2)
        self.assertEqual(result.output, {"items": [1]})

    def test_invalid_invocation_shapes_do_not_resolve_registry(self):
        cases = [
            dict(package="bytes"),
            dict(invocation={"name": "Ada"}),
            dict(timeout_seconds=True),
            dict(timeout_seconds=0),
            dict(cancel=object()),
            dict(skill_id="Bad Name"),
        ]
        for changes in cases:
            self.registry.calls = 0
            with self.assertRaises(SignedSkillError):
                self.execute(**changes)
            self.assertEqual(self.registry.calls, 0)


if __name__ == "__main__":
    unittest.main()
