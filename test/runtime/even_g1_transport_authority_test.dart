import 'dart:async';
import 'dart:typed_data';

import 'package:demo_ai_even/adapters/even_g1/even_g1_transport.dart';
import 'package:demo_ai_even/runtime/device_hal.dart';
import 'package:demo_ai_even/services/ble.dart';
import 'package:flutter_test/flutter_test.dart';

final class _FakeConnectionSource implements BleConnectionSource {
  _FakeConnectionSource(this._snapshot);

  final StreamController<BleConnectionSnapshot> _controller =
      StreamController<BleConnectionSnapshot>.broadcast();
  BleConnectionSnapshot _snapshot;

  @override
  BleConnectionSnapshot get connectionSnapshot => _snapshot;

  @override
  Stream<BleConnectionSnapshot> get connectionSnapshots => _controller.stream;

  void publish(BleConnectionSnapshot value) {
    _snapshot = value;
    _controller.add(value);
  }

  Future<void> close() => _controller.close();
}

void main() {
  late _FakeConnectionSource source;
  late List<Map<String, Object>> calls;
  late EvenG1Transport transport;

  Future<BleReceive> acceptedSender(
    Uint8List bytes, {
    required String lr,
    required int timeoutMs,
    required int expectedGeneration,
    required String expectedPairIdentity,
  }) async {
    calls.add(<String, Object>{
      'side': lr,
      'generation': expectedGeneration,
      'pair': expectedPairIdentity,
      'command': bytes.first,
      'timeout': timeoutMs,
    });
    return BleReceive()
      ..lr = lr
      ..data = Uint8List.fromList(<int>[bytes.first, 0xc9])
      ..generation = expectedGeneration
      ..pairIdentity = expectedPairIdentity;
  }

  setUp(() {
    calls = <Map<String, Object>>[];
    source = _FakeConnectionSource(
      const BleConnectionSnapshot(
        leftConnected: true,
        rightConnected: true,
        generation: 7,
        pairIdentity: 'Pair_45',
      ),
    );
    transport = EvenG1Transport(
      manager: source,
      requestSender: acceptedSender,
    );
  });

  tearDown(() async {
    await transport.dispose();
    await source.close();
  });

  test('same caller key cannot alias left and right legs', () async {
    final bytes = Uint8List.fromList(<int>[0x4e, 0x01]);

    final left = await transport.send(
      side: GlassesSide.left,
      bytes: bytes,
      timeout: const Duration(milliseconds: 200),
      idempotencyKey: 'display-1',
    );
    final right = await transport.send(
      side: GlassesSide.right,
      bytes: bytes,
      timeout: const Duration(milliseconds: 200),
      idempotencyKey: 'display-1',
    );

    expect(left.accepted, isTrue);
    expect(right.accepted, isTrue);
    expect(calls.map((Map<String, Object> call) => call['side']),
        <String>['L', 'R']);
  });

  test('same caller key is a new authority after reconnect generation',
      () async {
    final bytes = Uint8List.fromList(<int>[0x25, 0x01]);
    await transport.send(
      side: GlassesSide.left,
      bytes: bytes,
      timeout: const Duration(milliseconds: 200),
      idempotencyKey: 'heartbeat-1',
    );

    source.publish(
      const BleConnectionSnapshot(
        leftConnected: true,
        rightConnected: true,
        generation: 8,
        pairIdentity: 'Pair_45',
      ),
    );
    await transport.send(
      side: GlassesSide.left,
      bytes: bytes,
      timeout: const Duration(milliseconds: 200),
      idempotencyKey: 'heartbeat-1',
    );

    expect(calls.length, 2);
    expect(calls[0]['generation'], 7);
    expect(calls[1]['generation'], 8);
  });

  test('same caller key is a new authority for a different pair', () async {
    final bytes = Uint8List.fromList(<int>[0x18, 0x00]);
    await transport.send(
      side: GlassesSide.right,
      bytes: bytes,
      timeout: const Duration(milliseconds: 200),
      idempotencyKey: 'exit-1',
    );

    source.publish(
      const BleConnectionSnapshot(
        leftConnected: true,
        rightConnected: true,
        generation: 7,
        pairIdentity: 'Pair_91',
      ),
    );
    await transport.send(
      side: GlassesSide.right,
      bytes: bytes,
      timeout: const Duration(milliseconds: 200),
      idempotencyKey: 'exit-1',
    );

    expect(calls.length, 2);
    expect(calls[0]['pair'], 'Pair_45');
    expect(calls[1]['pair'], 'Pair_91');
  });

  test('same scoped authority rejects argument drift', () async {
    await transport.send(
      side: GlassesSide.left,
      bytes: Uint8List.fromList(<int>[0x0e, 0x01]),
      timeout: const Duration(milliseconds: 200),
      idempotencyKey: 'microphone-1',
    );

    expect(
      () => transport.send(
        side: GlassesSide.left,
        bytes: Uint8List.fromList(<int>[0x0e, 0x00]),
        timeout: const Duration(milliseconds: 200),
        idempotencyKey: 'microphone-1',
      ),
      throwsStateError,
    );
    expect(calls.length, 1);
  });

  test('native request receives the captured authority tuple', () async {
    await transport.send(
      side: GlassesSide.right,
      bytes: Uint8List.fromList(<int>[0x15, 0x03]),
      timeout: const Duration(milliseconds: 321),
      idempotencyKey: 'bitmap-3',
    );

    expect(calls.single, <String, Object>{
      'side': 'R',
      'generation': 7,
      'pair': 'Pair_45',
      'command': 0x15,
      'timeout': 321,
    });
  });

  test('missing connection authority rejects before native write', () async {
    source.publish(
      const BleConnectionSnapshot(
        leftConnected: true,
        rightConnected: true,
        generation: 0,
      ),
    );

    final result = await transport.send(
      side: GlassesSide.left,
      bytes: Uint8List.fromList(<int>[0x25, 0x01]),
      timeout: const Duration(milliseconds: 200),
      idempotencyKey: 'no-authority',
    );

    expect(result.retrySafe, isTrue);
    expect(result.errorCode, 'connection_authority_unavailable');
    expect(calls, isEmpty);
  });
}
