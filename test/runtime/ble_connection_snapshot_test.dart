import 'package:demo_ai_even/services/ble.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('dual-leg snapshot exposes degraded and complete states', () {
    const degraded = BleConnectionSnapshot(
      leftConnected: true,
      rightConnected: false,
      generation: 7,
    );
    const complete = BleConnectionSnapshot(
      leftConnected: true,
      rightConnected: true,
      generation: 8,
    );
    expect(degraded.bothConnected, isFalse);
    expect(complete.bothConnected, isTrue);
  });
}
