import 'package:demo_ai_even/ble_manager.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const channel = MethodChannel('method.bluetooth');
  final manager = BleManager.get();

  setUp(() async {
    manager.resetAuthorityForTest();
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (MethodCall call) async {
      if (call.method == BleManager.methodSend) {
        return true;
      }
      return null;
    });
    await manager.handleNativeMethodForTest(
      const MethodCall('glassesConnected', <String, Object>{
        'leftDeviceName': 'G1_45_L_test',
        'rightDeviceName': 'G1_45_R_test',
        'left_connected': true,
        'right_connected': true,
        'generation': 41,
        'pairIdentity': 'Pair_45',
      }),
    );
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
}
