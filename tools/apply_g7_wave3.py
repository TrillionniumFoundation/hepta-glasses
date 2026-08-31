#!/usr/bin/env python3
"""Add deterministic regression tests for the G7 closure fixes."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def main() -> int:
    write(
        "services/control_plane/test_concurrency_g7.py",
        '''from __future__ import annotations\n\nimport threading\nimport time\nimport unittest\nfrom concurrent.futures import ThreadPoolExecutor\nfrom types import SimpleNamespace\n\nfrom services.control_plane.capabilities import (\n    AuditJournal,\n    CapabilityGateway,\n    CapabilityRequest,\n    CapabilitySpec,\n    DecisionLease,\n    RiskTier,\n    TrustClass,\n    canonical_digest,\n)\nfrom services.control_plane.realtime import (\n    RealtimeError,\n    RealtimeSession,\n    RealtimeSessionBroker,\n    SessionState,\n)\n\n\nclass _CountingAdapter:\n    def __init__(self) -> None:\n        self.count = 0\n        self.lock = threading.Lock()\n\n    def execute(self, request: CapabilityRequest):\n        with self.lock:\n            self.count += 1\n        time.sleep(0.01)\n        return {"authoritative": True, "external_id": request.idempotency_key}\n\n    def reconcile(self, request: CapabilityRequest, external_id: str):\n        return {"authoritative": True, "external_id": external_id}\n\n\nclass _BootstrapTokens:\n    def verify(self, *_args, **_kwargs):\n        return SimpleNamespace(\n            token_id="token-1",\n            session_id="session-1",\n            subject="subject-1",\n            device_id="device-1",\n        )\n\n\nclass ConcurrencyClosureTests(unittest.TestCase):\n    def test_audit_append_is_thread_safe(self) -> None:\n        journal = AuditJournal()\n        with ThreadPoolExecutor(max_workers=8) as executor:\n            list(\n                executor.map(\n                    lambda index: journal.append("event", {"index": index}),\n                    range(128),\n                )\n            )\n        journal.verify()\n        self.assertEqual(\n            [entry["sequence"] for entry in journal.entries],\n            list(range(1, 129)),\n        )\n\n    def test_same_capability_idempotency_key_executes_once(self) -> None:\n        journal = AuditJournal()\n        gateway = CapabilityGateway(journal=journal, clock=lambda: 100)\n        adapter = _CountingAdapter()\n        gateway.register(\n            CapabilitySpec(\n                name="reminder.create",\n                risk=RiskTier.R2,\n                mutating=True,\n                required_fields=frozenset({"title"}),\n                reconciliation_supported=True,\n            ),\n            adapter,\n        )\n        arguments = {"title": "Review G7"}\n        request = CapabilityRequest(\n            request_id="request-1",\n            task_id="task-1",\n            subject="subject-1",\n            device_id="device-1",\n            name="reminder.create",\n            arguments=arguments,\n            idempotency_key="idem-1",\n            deadline=200,\n            origin=TrustClass.USER,\n        )\n        lease = DecisionLease(\n            lease_id="lease-1",\n            subject="subject-1",\n            device_id="device-1",\n            task_id="task-1",\n            action="reminder.create",\n            argument_digest=canonical_digest(arguments),\n            expires_at=200,\n            biometric_verified=False,\n        )\n        with ThreadPoolExecutor(max_workers=2) as executor:\n            receipts = list(\n                executor.map(\n                    lambda _index: gateway.execute(request, lease=lease),\n                    range(2),\n                )\n            )\n        self.assertEqual(adapter.count, 1)\n        self.assertEqual({receipt.status for receipt in receipts}, {"succeeded"})\n        self.assertEqual(sum(receipt.replayed for receipt in receipts), 1)\n\n    def test_realtime_bootstrap_token_is_consumed_once(self) -> None:\n        broker = RealtimeSessionBroker(\n            access_tokens=object(),\n            bootstrap_tokens=_BootstrapTokens(),\n            rate_limiter=object(),\n            allowed_provider_profiles={"development"},\n            clock=lambda: 100,\n        )\n        broker._sessions["session-1"] = RealtimeSession(\n            session_id="session-1",\n            subject="subject-1",\n            device_id="device-1",\n            state=SessionState.ISSUED,\n            generation=0,\n            created_at=100,\n            expires_at=200,\n            microphone_indicator=False,\n            provider_profile="development",\n        )\n\n        def activate(_index: int) -> str:\n            try:\n                broker.activate("bootstrap")\n                return "activated"\n            except RealtimeError as error:\n                return error.code\n\n        with ThreadPoolExecutor(max_workers=2) as executor:\n            outcomes = list(executor.map(activate, range(2)))\n        self.assertEqual(outcomes.count("activated"), 1)\n        self.assertEqual(outcomes.count("bootstrap_ticket_replayed"), 1)\n\n\nif __name__ == "__main__":\n    unittest.main()\n''',
    )
    write(
        "test/views/even_list_page_test.dart",
        '''import 'package:demo_ai_even/controllers/evenai_model_controller.dart';\nimport 'package:demo_ai_even/services/evenai.dart';\nimport 'package:demo_ai_even/views/even_list_page.dart';\nimport 'package:flutter/material.dart';\nimport 'package:flutter_test/flutter_test.dart';\nimport 'package:get/get.dart';\n\nvoid main() {\n  setUp(() {\n    Get.testMode = true;\n    EvenAI.isEvenAISyncing.value = false;\n    Get.put(EvenaiModelController());\n  });\n\n  tearDown(() {\n    Get.reset();\n    EvenAI.isEvenAISyncing.value = false;\n  });\n\n  testWidgets('history row expands without ParentDataWidget errors', (tester) async {\n    final controller = Get.find<EvenaiModelController>()\n      ..addItem('Question', 'Answer');\n\n    await tester.pumpWidget(\n      const MaterialApp(home: EvenAIListPage()),\n    );\n    await tester.pumpAndSettle();\n\n    expect(find.text('Question'), findsOneWidget);\n    expect(find.text('Answer'), findsNothing);\n    await tester.tap(find.text('Question'));\n    await tester.pumpAndSettle();\n\n    expect(find.text('Answer'), findsOneWidget);\n    expect(tester.takeException(), isNull);\n  });\n}\n''',
    )
    write(
        "test/controllers/bmp_update_manager_test.dart",
        '''import 'dart:typed_data';\n\nimport 'package:demo_ai_even/controllers/bmp_update_manager.dart';\nimport 'package:flutter_test/flutter_test.dart';\n\nvoid main() {\n  test('bitmap transfer rejects invalid side before any device effect', () async {\n    await expectLater(\n      BmpUpdateManager().updateBmp('X', Uint8List.fromList(<int>[1])),\n      throwsArgumentError,\n    );\n  });\n\n  test('bitmap transfer rejects empty and oversized payloads', () async {\n    final manager = BmpUpdateManager();\n    expect(await manager.updateBmp('L', Uint8List(0)), isFalse);\n    expect(await manager.updateBmp('R', Uint8List(194 * 256 + 1)), isFalse);\n  });\n}\n''',
    )
    write(
        "test/runtime/device_effect_scheduler_close_test.dart",
        '''import 'dart:async';\n\nimport 'package:demo_ai_even/runtime/device_effect_scheduler.dart';\nimport 'package:flutter_test/flutter_test.dart';\n\nvoid main() {\n  test('scheduler close is bounded while an effect is stuck', () async {\n    final scheduler = DeviceEffectScheduler();\n    final release = Completer<void>();\n    final effect = scheduler.schedule<void>('blocked', () => release.future);\n\n    await expectLater(\n      scheduler.close(timeout: const Duration(milliseconds: 10)),\n      throwsA(isA<TimeoutException>()),\n    );\n    release.complete();\n    await effect;\n    await scheduler.close();\n  });\n}\n''',
    )
    for path in (
        ROOT / "tools/apply_g7_wave3.py",
        ROOT / "tools/apply_g7_wave2.py",
        ROOT / "tools/apply_g7_repair.py",
        ROOT / "tools/apply_g7_synthesis.py",
    ):
        if path.exists():\n            path.chmod(0o755)\n    subprocess.run(["git", "add", "-A"], cwd=ROOT, check=True)\n    return 0\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n'''.replace('if path.exists():\\n', 'if path.exists():\n').replace('path.chmod(0o755)\\n', 'path.chmod(0o755)\n').replace('check=True)\\n', 'check=True)\n').replace('return 0\\n', 'return 0\n').replace('main())\\n', 'main())\n'),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
