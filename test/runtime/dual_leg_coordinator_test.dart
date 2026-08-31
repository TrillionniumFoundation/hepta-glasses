import 'dart:typed_data';

import 'package:demo_ai_even/runtime/device_hal.dart';
import 'package:demo_ai_even/runtime/dual_leg_coordinator.dart';
import 'package:demo_ai_even/simulator/g1_digital_twin.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test(
    'dual-leg coordinator retries only a proven pre-write timeout',
    () async {
      final twin = G1DigitalTwin();
      addTearDown(twin.dispose);
      twin.injectTimeouts(GlassesSide.left, 1);
      final coordinator = DualLegCoordinator(transport: twin, maxAttempts: 3);
      final bytes = Uint8List.fromList(<int>[0x4e, 0x01, 0x00]);

      final first = await coordinator.sendMirrored(
        bytes: bytes,
        idempotencyKey: 'logical-write-1',
      );
      final replay = await coordinator.sendMirrored(
        bytes: bytes,
        idempotencyKey: 'logical-write-1',
      );

      expect(first.complete, isTrue);
      expect(replay.replayed, isTrue);
      expect(twin.writes, hasLength(2));
      expect(twin.sendAttempts, 3);
    },
  );

  test(
    'ack loss after write is indeterminate and never blindly retried',
    () async {
      final twin = G1DigitalTwin();
      addTearDown(twin.dispose);
      twin.injectIndeterminateAfterWrites(GlassesSide.left, 1);
      final coordinator = DualLegCoordinator(transport: twin, maxAttempts: 3);

      final receipt = await coordinator.sendMirrored(
        bytes: Uint8List.fromList(<int>[0x4e, 0x02, 0x00]),
        idempotencyKey: 'ack-lost-write',
      );

      expect(receipt.complete, isFalse);
      expect(receipt.requiresReconciliation, isTrue);
      expect(receipt.left.effectMayHaveOccurred, isTrue);
      expect(twin.sendAttempts, 2);
      expect(twin.writes, hasLength(2));

      final reconciled = await coordinator.reconcile(
        idempotencyKey: 'ack-lost-write',
        reconciler: (GlassesSide side, TransportAck prior) async =>
            TransportAck(
              accepted: true,
              timeout: false,
              sequence: prior.sequence,
              effectMayHaveOccurred: true,
            ),
      );
      expect(reconciled.complete, isTrue);
      expect(reconciled.reconciled, isTrue);
      expect(twin.sendAttempts, 2);
    },
  );

  test('single-leg failure is explicit degraded state', () async {
    final twin = G1DigitalTwin();
    addTearDown(twin.dispose);
    twin.setConnected(GlassesSide.right, false);
    final coordinator = DualLegCoordinator(transport: twin, maxAttempts: 2);

    final receipt = await coordinator.sendMirrored(
      bytes: Uint8List.fromList(<int>[1, 2, 3]),
      idempotencyKey: 'degraded-write',
    );

    expect(receipt.degraded, isTrue);
    expect(receipt.left.accepted, isTrue);
    expect(receipt.right.errorCode, 'side_disconnected');
  });
}
