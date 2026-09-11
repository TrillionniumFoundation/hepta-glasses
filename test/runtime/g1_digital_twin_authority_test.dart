import 'dart:typed_data';

import 'package:demo_ai_even/runtime/device_hal.dart';
import 'package:demo_ai_even/simulator/g1_digital_twin.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('caller key is isolated by side generation and pair', () async {
    final twin = G1DigitalTwin();
    addTearDown(twin.dispose);
    final bytes = Uint8List.fromList(<int>[0x4e, 0x01, 0x02]);

    await twin.send(
      side: GlassesSide.left,
      bytes: bytes,
      timeout: const Duration(seconds: 1),
      idempotencyKey: 'shared-key',
    );
    await twin.send(
      side: GlassesSide.right,
      bytes: bytes,
      timeout: const Duration(seconds: 1),
      idempotencyKey: 'shared-key',
    );
    twin.advanceGeneration();
    await twin.send(
      side: GlassesSide.left,
      bytes: bytes,
      timeout: const Duration(seconds: 1),
      idempotencyKey: 'shared-key',
    );
    twin.advanceGeneration(pairIdentity: 'digital-twin-pair-2');
    await twin.send(
      side: GlassesSide.left,
      bytes: bytes,
      timeout: const Duration(seconds: 1),
      idempotencyKey: 'shared-key',
    );

    expect(twin.writes, hasLength(4));
    expect(twin.writes.map((write) => write.side), <GlassesSide>[
      GlassesSide.left,
      GlassesSide.right,
      GlassesSide.left,
      GlassesSide.left,
    ]);
    expect(twin.writes.map((write) => write.generation), <int>[1, 1, 2, 3]);
    expect(twin.writes.map((write) => write.pairIdentity), <String>[
      'digital-twin-pair-1',
      'digital-twin-pair-1',
      'digital-twin-pair-1',
      'digital-twin-pair-2',
    ]);
  });

  test(
    'same complete identity returns receipt without another write',
    () async {
      final twin = G1DigitalTwin();
      addTearDown(twin.dispose);
      final bytes = Uint8List.fromList(<int>[0x25, 0x01]);

      final first = await twin.send(
        side: GlassesSide.left,
        bytes: bytes,
        timeout: const Duration(seconds: 1),
        idempotencyKey: 'receipt-key',
      );
      final replay = await twin.send(
        side: GlassesSide.left,
        bytes: bytes,
        timeout: const Duration(seconds: 1),
        idempotencyKey: 'receipt-key',
      );

      expect(first.accepted, isTrue);
      expect(replay.sequence, first.sequence);
      expect(twin.writes, hasLength(1));
      expect(twin.sendAttempts, 1);
    },
  );

  test('payload drift in the same authority scope fails closed', () async {
    final twin = G1DigitalTwin();
    addTearDown(twin.dispose);

    await twin.send(
      side: GlassesSide.right,
      bytes: Uint8List.fromList(<int>[1, 2, 3]),
      timeout: const Duration(seconds: 1),
      idempotencyKey: 'drift-key',
    );

    await expectLater(
      twin.send(
        side: GlassesSide.right,
        bytes: Uint8List.fromList(<int>[1, 2, 4]),
        timeout: const Duration(seconds: 1),
        idempotencyKey: 'drift-key',
      ),
      throwsStateError,
    );
    expect(twin.writes, hasLength(1));
  });
}
