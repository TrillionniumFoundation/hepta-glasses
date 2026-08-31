import 'dart:typed_data';

import 'package:demo_ai_even/controllers/bmp_update_manager.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('BMP packets preserve payload and one-byte sequence bounds', () {
    final payload = Uint8List.fromList(
        List<int>.generate(400, (int index) => index & 0xff));
    final packets = BmpTransferCodec.buildPackets(payload);
    expect(packets, hasLength(3));
    expect(packets.first.sublist(0, 6), <int>[0x15, 0, 0, 0x1c, 0, 0]);
    expect(packets[1].sublist(0, 2), <int>[0x15, 1]);
    final rebuilt = <int>[
      ...packets.first.sublist(6),
      ...packets[1].sublist(2),
      ...packets[2].sublist(2)
    ];
    expect(rebuilt, payload);
  });

  test('BMP codec rejects empty and oversized payloads', () {
    expect(
        () => BmpTransferCodec.buildPackets(Uint8List(0)), throwsArgumentError);
    expect(
        () => BmpTransferCodec.buildPackets(
            Uint8List(BmpTransferCodec.maximumImageBytes + 1)),
        throwsArgumentError);
  });

  test('BMP response parsing fails closed on short responses', () {
    expect(BmpTransferCodec.responseStatus(Uint8List(0)), isNull);
    expect(BmpTransferCodec.responseStatus(Uint8List.fromList(<int>[0x16])),
        isNull);
    expect(
        BmpTransferCodec.isSuccessResponse(
            Uint8List.fromList(<int>[0x20, 0xc9])),
        isTrue);
    expect(
        BmpTransferCodec.isSuccessResponse(
            Uint8List.fromList(<int>[0x16, 0, 0, 0, 0, 0xc9])),
        isTrue);
    expect(
        BmpTransferCodec.isSuccessResponse(
            Uint8List.fromList(<int>[0x16, 0, 0, 0, 0])),
        isFalse);
  });
}
