import 'dart:typed_data';

import 'package:demo_ai_even/runtime/device_hal.dart';
import 'package:demo_ai_even/runtime/dual_leg_coordinator.dart';
import 'package:demo_ai_even/simulator/g1_digital_twin.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('dual-leg coordinator retries and replays without duplicate writes', () async {
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
  });

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
