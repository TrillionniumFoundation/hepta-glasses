import 'dart:typed_data';

import 'package:demo_ai_even/services/ble.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('BLE response parses exact connection authority and bytes', () {
    final response = BleReceive.fromMap(<String, Object?>{
      'lr': 'L',
      'data': Uint8List.fromList(<int>[0x25, 0xc9]),
      'type': 'Receive',
      'generation': 7,
      'pairIdentity': ' Pair_45 ',
    });

    expect(response.lr, 'L');
    expect(response.getCmd(), 0x25);
    expect(response.generation, 7);
    expect(response.pairIdentity, 'Pair_45');
    expect(response.hasAuthoritativeIdentity, isTrue);
    expect(response.isTimeout, isFalse);
  });

  test('missing or placeholder connection authority fails closed', () {
    final variants = <BleReceive>[
      BleReceive.fromMap(<String, Object?>{
        'lr': 'L',
        'data': Uint8List.fromList(<int>[0x25, 0xc9]),
        'pairIdentity': 'Pair_45',
      }),
      BleReceive.fromMap(<String, Object?>{
        'lr': 'L',
        'data': Uint8List.fromList(<int>[0x25, 0xc9]),
        'generation': 0,
        'pairIdentity': 'Pair_45',
      }),
      BleReceive.fromMap(<String, Object?>{
        'lr': 'L',
        'data': Uint8List.fromList(<int>[0x25, 0xc9]),
        'generation': 7,
      }),
      BleReceive.fromMap(<String, Object?>{
        'lr': 'L',
        'data': Uint8List.fromList(<int>[0x25, 0xc9]),
        'generation': 7,
        'pairIdentity': unselectedBlePairIdentity,
      }),
      BleReceive.fromMap(<String, Object?>{
        'lr': 'L',
        'data': Uint8List.fromList(<int>[0x25, 0xc9]),
        'generation': 7,
        'pairIdentity': '   ',
      }),
    ];

    expect(
      variants
          .every((BleReceive response) => !response.hasAuthoritativeIdentity),
      isTrue,
    );
  });

  test('empty BLE response fails closed when command is requested', () {
    final response = BleReceive();
    expect(response.getCmd, throwsStateError);
  });
}
