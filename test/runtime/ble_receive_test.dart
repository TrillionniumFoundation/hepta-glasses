import 'dart:typed_data';

import 'package:demo_ai_even/services/ble.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('BLE response parses connection generation and bytes', () {
    final response = BleReceive.fromMap(<String, Object?>{
      'lr': 'L',
      'data': Uint8List.fromList(<int>[0x25, 0xc9]),
      'type': 'Receive',
      'generation': 7,
    });

    expect(response.lr, 'L');
    expect(response.getCmd(), 0x25);
    expect(response.generation, 7);
    expect(response.isTimeout, isFalse);
  });

  test('empty BLE response fails closed when command is requested', () {
    final response = BleReceive();
    expect(response.getCmd, throwsStateError);
  });
}
