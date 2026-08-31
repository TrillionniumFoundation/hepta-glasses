#!/usr/bin/env python3
"""Install deterministic regression tests for the G7 closure fixes."""

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
        '''from __future__ import annotations

import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from services.control_plane.capabilities import (
    AuditJournal,
    CapabilityGateway,
    CapabilityRequest,
    CapabilitySpec,
    DecisionLease,
    RiskTier,
    TrustClass,
    canonical_digest,
)
from services.control_plane.realtime import (
    RealtimeError,
    RealtimeSession,
    RealtimeSessionBroker,
    SessionState,
)


class _CountingAdapter:
    def __init__(self) -> None:
        self.count = 0
        self.lock = threading.Lock()

    def execute(self, request: CapabilityRequest):
        with self.lock:
            self.count += 1
        time.sleep(0.01)
        return {"authoritative": True, "external_id": request.idempotency_key}

    def reconcile(self, request: CapabilityRequest, external_id: str):
        return {"authoritative": True, "external_id": external_id}


class _BootstrapTokens:
    def verify(self, *_args, **_kwargs):
        return SimpleNamespace(
            token_id="token-1",
            session_id="session-1",
            subject="subject-1",
            device_id="device-1",
        )


class ConcurrencyClosureTests(unittest.TestCase):
    def test_audit_append_is_thread_safe(self) -> None:
        journal = AuditJournal()
        with ThreadPoolExecutor(max_workers=8) as executor:
            list(
                executor.map(
                    lambda index: journal.append("event", {"index": index}),
                    range(128),
                )
            )
        journal.verify()
        self.assertEqual(
            [entry["sequence"] for entry in journal.entries],
            list(range(1, 129)),
        )

    def test_same_capability_idempotency_key_executes_once(self) -> None:
        journal = AuditJournal()
        gateway = CapabilityGateway(journal=journal, clock=lambda: 100)
        adapter = _CountingAdapter()
        gateway.register(
            CapabilitySpec(
                name="reminder.create",
                risk=RiskTier.R2,
                mutating=True,
                required_fields=frozenset({"title"}),
                reconciliation_supported=True,
            ),
            adapter,
        )
        arguments = {"title": "Review G7"}
        request = CapabilityRequest(
            request_id="request-1",
            task_id="task-1",
            subject="subject-1",
            device_id="device-1",
            name="reminder.create",
            arguments=arguments,
            idempotency_key="idem-1",
            deadline=200,
            origin=TrustClass.USER,
        )
        lease = DecisionLease(
            lease_id="lease-1",
            subject="subject-1",
            device_id="device-1",
            task_id="task-1",
            action="reminder.create",
            argument_digest=canonical_digest(arguments),
            expires_at=200,
            biometric_verified=False,
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            receipts = list(
                executor.map(
                    lambda _index: gateway.execute(request, lease=lease),
                    range(2),
                )
            )
        self.assertEqual(adapter.count, 1)
        self.assertEqual({receipt.status for receipt in receipts}, {"succeeded"})
        self.assertEqual(sum(receipt.replayed for receipt in receipts), 1)

    def test_realtime_bootstrap_token_is_consumed_once(self) -> None:
        broker = RealtimeSessionBroker(
            access_tokens=object(),
            bootstrap_tokens=_BootstrapTokens(),
            rate_limiter=object(),
            allowed_provider_profiles={"development"},
            clock=lambda: 100,
        )
        broker._sessions["session-1"] = RealtimeSession(
            session_id="session-1",
            subject="subject-1",
            device_id="device-1",
            state=SessionState.ISSUED,
            generation=0,
            created_at=100,
            expires_at=200,
            microphone_indicator=False,
            provider_profile="development",
        )

        def activate(_index: int) -> str:
            try:
                broker.activate("bootstrap")
                return "activated"
            except RealtimeError as error:
                return error.code

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(activate, range(2)))
        self.assertEqual(outcomes.count("activated"), 1)
        self.assertEqual(outcomes.count("bootstrap_ticket_replayed"), 1)


if __name__ == "__main__":
    unittest.main()
''',
    )
    write(
        "test/views/even_list_page_test.dart",
        '''import 'package:demo_ai_even/controllers/evenai_model_controller.dart';
import 'package:demo_ai_even/services/evenai.dart';
import 'package:demo_ai_even/views/even_list_page.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:get/get.dart';

void main() {
  setUp(() {
    Get.testMode = true;
    EvenAI.isEvenAISyncing.value = false;
    Get.put(EvenaiModelController());
  });

  tearDown(() {
    Get.reset();
    EvenAI.isEvenAISyncing.value = false;
  });

  testWidgets('history row expands without ParentDataWidget errors',
      (WidgetTester tester) async {
    final controller = Get.find<EvenaiModelController>()
      ..addItem('Question', 'Answer');

    await tester.pumpWidget(
      const MaterialApp(home: EvenAIListPage()),
    );
    await tester.pumpAndSettle();

    expect(find.text('Question'), findsOneWidget);
    expect(find.text('Answer'), findsNothing);
    await tester.tap(find.text('Question'));
    await tester.pumpAndSettle();

    expect(find.text('Answer'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
''',
    )
    write(
        "test/controllers/bmp_update_manager_test.dart",
        '''import 'dart:typed_data';

import 'package:demo_ai_even/controllers/bmp_update_manager.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('bitmap transfer rejects invalid side before any device effect',
      () async {
    await expectLater(
      BmpUpdateManager().updateBmp('X', Uint8List.fromList(<int>[1])),
      throwsArgumentError,
    );
  });

  test('bitmap transfer rejects empty and oversized payloads', () async {
    final manager = BmpUpdateManager();
    expect(await manager.updateBmp('L', Uint8List(0)), isFalse);
    expect(await manager.updateBmp('R', Uint8List(194 * 256 + 1)), isFalse);
  });
}
''',
    )
    write(
        "test/runtime/device_effect_scheduler_close_test.dart",
        '''import 'dart:async';

import 'package:demo_ai_even/runtime/device_effect_scheduler.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('scheduler close is bounded while an effect is stuck', () async {
    final scheduler = DeviceEffectScheduler();
    final release = Completer<void>();
    final effect = scheduler.schedule<void>('blocked', () => release.future);

    await expectLater(
      scheduler.close(timeout: const Duration(milliseconds: 10)),
      throwsA(isA<TimeoutException>()),
    );
    release.complete();
    await effect;
    await scheduler.close();
  });
}
''',
    )
    broken = ROOT / "tools/apply_g7_wave3.py"
    if broken.exists():
        broken.unlink()
    for path in (
        ROOT / "tools/apply_g7_wave3_fixed.py",
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
