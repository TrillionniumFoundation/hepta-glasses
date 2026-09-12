"""Process-local Signed Registry configuration custody regressions.

These tests use inert public-key bytes and real SQLite. They do not establish a
production trust root, hostile-interpreter isolation, or external authority.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from services.skills.signed_package import (
    PublisherKey,
    SPKI_PREFIX,
    SignedSkillError,
)
from services.skills.signed_registry import SignedSkillRegistry


class SignedRegistryRuntimePolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "registry.sqlite")
        self.now = 1000
        self.source_keys = {
            "publisher-v1": PublisherKey(
                "publisher", SPKI_PREFIX + b"r" * 32, 900, 2000
            )
        }

    def open(self, **changes) -> SignedSkillRegistry:
        options = dict(
            subject="user",
            keys=self.source_keys,
            allowed_capabilities=frozenset({"display.text"}),
            allowed_domains=frozenset({"service.example"}),
            clock=lambda: self.now,
            maximum_entries=17,
        )
        options.update(changes)
        registry = SignedSkillRegistry(self.path, **options)
        self.addCleanup(registry.close)
        return registry

    def test_public_policy_bindings_are_read_only(self) -> None:
        registry = self.open()
        replacements = {
            "subject": "other",
            "keys": {},
            "capabilities": frozenset({"shell"}),
            "domains": frozenset({"other.example"}),
            "clock": lambda: 1,
            "maximum_entries": 10000,
            "transparency_verifier": object(),
            "state_anchor": object(),
        }
        for attribute, replacement in replacements.items():
            with self.subTest(attribute=attribute), self.assertRaises(AttributeError):
                setattr(registry, attribute, replacement)

    def test_exposed_policy_matches_the_persisted_constructor_binding(self) -> None:
        registry = self.open()
        self.assertEqual(registry.subject, "user")
        self.assertEqual(set(registry.keys), {"publisher-v1"})
        self.assertEqual(registry.capabilities, frozenset({"display.text"}))
        self.assertEqual(registry.domains, frozenset({"service.example"}))
        self.assertEqual(registry.maximum_entries, 17)
        self.assertIsNone(registry.transparency_verifier)
        self.assertIsNone(registry.state_anchor)

    def test_caller_key_mapping_is_copied_and_exposed_read_only(self) -> None:
        keys = dict(self.source_keys)
        registry = self.open(keys=keys)
        keys.clear()
        self.assertEqual(set(registry.keys), {"publisher-v1"})
        with self.assertRaises(TypeError):
            registry.keys["replacement"] = self.source_keys["publisher-v1"]  # type: ignore[index]

    def test_caller_policy_sets_cannot_be_mutated_through_registry(self) -> None:
        registry = self.open()
        with self.assertRaises(AttributeError):
            registry.capabilities.add("shell")  # type: ignore[attr-defined]
        with self.assertRaises(AttributeError):
            registry.domains.add("other.example")  # type: ignore[attr-defined]

    def test_clock_exception_is_sanitized_during_fresh_initialization(self) -> None:
        marker = "private-clock-exception-marker"

        def broken_clock() -> int:
            raise RuntimeError(marker)

        with self.assertRaises(SignedSkillError) as caught:
            self.open(clock=broken_clock)
        self.assertEqual(caught.exception.code, "skill_clock_invalid")
        self.assertIsNone(caught.exception.__cause__)
        self.assertTrue(caught.exception.__suppress_context__)
        self.assertNotIn(marker, repr(caught.exception))

    def test_clock_exception_after_open_is_sanitized_and_registry_recovers(self) -> None:
        marker = "private-running-clock-marker"
        state = {"broken": False}

        def clock() -> int:
            if state["broken"]:
                raise RuntimeError(marker)
            return self.now

        registry = self.open(clock=clock)
        before = registry.state_checkpoint()
        state["broken"] = True
        with self.assertRaises(SignedSkillError) as caught:
            registry.resolve("unknown", package=b"")
        self.assertEqual(caught.exception.code, "skill_clock_invalid")
        self.assertIsNone(caught.exception.__cause__)
        self.assertNotIn(marker, repr(caught.exception))
        state["broken"] = False
        after = registry.state_checkpoint()
        self.assertEqual(
            (before.instance_id, before.revision, before.authority_digest),
            (after.instance_id, after.revision, after.authority_digest),
        )

    def test_invalid_clock_value_uses_the_same_fixed_error(self) -> None:
        with self.assertRaises(SignedSkillError) as caught:
            self.open(clock=lambda: True)
        self.assertEqual(caught.exception.code, "skill_clock_invalid")


if __name__ == "__main__":
    unittest.main()
