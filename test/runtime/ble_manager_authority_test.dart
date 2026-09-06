import 'package:demo_ai_even/ble_manager.dart';
import 'package:demo_ai_even/services/ble.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const channel = MethodChannel('method.bluetooth');
  final manager = BleManager.get();

  BleReceive responseFor(
    int command, {
    int generation = 41,
    String pairIdentity = 'Pair_45',
  }) =>
      BleReceive()
        ..lr = 'R'
        ..data = Uint8List.fromList(<int>[command, 0xc9])
        ..generation = generation
        ..pairIdentity = pairIdentity;

  Future<void> connect({int generation = 41}) =>
      manager.handleNativeMethodForTest(
        MethodCall('glassesConnected', <String, Object>{
          'leftDeviceName': 'G1_45_L_test',
          'rightDeviceName': 'G1_45_R_test',
          'left_connected': true,
          'right_connected': true,
          'generation': generation,
          'pairIdentity': 'Pair_45',
        }),
      );

  setUp(() async {
    manager.resetAuthorityForTest();
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (MethodCall call) async {
      if (call.method == BleManager.methodSend) {
        return true;
      }
      return null;
    });
    await connect();
  });

  tearDown(() {
    manager.resetAuthorityForTest();
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, null);
  });

  test('left disconnect cannot release an uncertain right-leg write', () async {
    final first = await BleManager.request(
      Uint8List.fromList(<int>[0x4e, 0x01]),
      lr: 'R',
      timeoutMs: 1,
      expectedGeneration: 41,
      expectedPairIdentity: 'Pair_45',
    );
    expect(first.isTimeout, isTrue);
    expect(first.effectMayHaveOccurred, isTrue);
    expect(first.errorCode, 'ack_timeout_after_native_write');

    manager.handleReceivedDataForTest(
      responseFor(
        0x4e,
        generation: 0,
        pairIdentity: unselectedBlePairIdentity,
      ),
    );

    await manager.handleNativeMethodForTest(
      const MethodCall('glassesDisconnected', <String, Object>{
        'leftDeviceName': 'G1_45_L_test',
        'rightDeviceName': 'G1_45_R_test',
        'left_connected': false,
        'right_connected': true,
        'side': 'L',
        'generation': 41,
        'pairIdentity': 'Pair_45',
      }),
    );

    final replay = await BleManager.request(
      Uint8List.fromList(<int>[0x4e, 0x01]),
      lr: 'R',
      timeoutMs: 1,
      expectedGeneration: 41,
      expectedPairIdentity: 'Pair_45',
    );
    expect(replay.isTimeout, isTrue);
    expect(replay.effectMayHaveOccurred, isTrue);
    expect(replay.errorCode, 'request_slot_quarantined');
  });

  test('unscoped or mismatched responses cannot complete a current slot',
      () async {
    final variants = <({String name, BleReceive Function(int) build})>[
      (
        name: 'missing generation',
        build: (int command) => BleReceive.fromMap(<String, Object?>{
              'lr': 'R',
              'data': Uint8List.fromList(<int>[command, 0xc9]),
              'pairIdentity': 'Pair_45',
            }),
      ),
      (
        name: 'zero generation',
        build: (int command) => responseFor(command, generation: 0),
      ),
      (
        name: 'missing pair',
        build: (int command) => BleReceive.fromMap(<String, Object?>{
              'lr': 'R',
              'data': Uint8List.fromList(<int>[command, 0xc9]),
              'generation': 41,
            }),
      ),
      (
        name: 'placeholder pair',
        build: (int command) => responseFor(
              command,
              pairIdentity: unselectedBlePairIdentity,
            ),
      ),
      (
        name: 'stale generation',
        build: (int command) => responseFor(command, generation: 40),
      ),
      (
        name: 'wrong pair',
        build: (int command) => responseFor(command, pairIdentity: 'Pair_91'),
      ),
    ];

    for (var index = 0; index < variants.length; index++) {
      final command = 0x60 + index;
      final future = BleManager.request(
        Uint8List.fromList(<int>[command, 0x01]),
        lr: 'R',
        timeoutMs: 200,
        expectedGeneration: 41,
        expectedPairIdentity: 'Pair_45',
      );
      var completed = false;
      future.then<void>((BleReceive _) {
        completed = true;
      });

      manager.handleReceivedDataForTest(variants[index].build(command));
      await Future<void>.delayed(const Duration(milliseconds: 5));
      expect(completed, isFalse, reason: variants[index].name);

      manager.handleReceivedDataForTest(responseFor(command));
      final accepted = await future;
      expect(accepted.isTimeout, isFalse, reason: variants[index].name);
      expect(accepted.hasAuthoritativeIdentity, isTrue);
    }
  });

  test('delayed unscoped response cannot cross into generation N plus one',
      () async {
    final old = BleManager.request(
      Uint8List.fromList(<int>[0x72, 0x01]),
      lr: 'R',
      timeoutMs: 200,
      expectedGeneration: 41,
      expectedPairIdentity: 'Pair_45',
    );
    await connect(generation: 42);
    final retired = await old;
    expect(retired.isTimeout, isTrue);
    expect(retired.errorCode, 'connection_generation_changed');

    final current = BleManager.request(
      Uint8List.fromList(<int>[0x72, 0x01]),
      lr: 'R',
      timeoutMs: 200,
      expectedGeneration: 42,
      expectedPairIdentity: 'Pair_45',
    );
    var completed = false;
    current.then<void>((BleReceive _) {
      completed = true;
    });

    manager.handleReceivedDataForTest(
      responseFor(
        0x72,
        generation: 0,
        pairIdentity: unselectedBlePairIdentity,
      ),
    );
    await Future<void>.delayed(const Duration(milliseconds: 5));
    expect(completed, isFalse);

    manager.handleReceivedDataForTest(responseFor(0x72, generation: 42));
    final accepted = await current;
    expect(accepted.isTimeout, isFalse);
    expect(accepted.generation, 42);
  });
}
