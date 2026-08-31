import 'dart:typed_data';

import 'package:demo_ai_even/controllers/bmp_update_manager.dart';
import 'package:demo_ai_even/services/ble.dart';
import 'package:flutter_test/flutter_test.dart';

BleReceive response(List<int> data) =>
    BleReceive()..data = Uint8List.fromList(data);

void main() {
  test('BMP transfer rejects invalid input before touching transport',
      () async {
    var sends = 0;
    final manager = BmpUpdateManager(
      sendPacket: (Uint8List packet, String side) async {
        sends++;
        return true;
      },
      request: (Uint8List packet, String side, int timeoutMs) async =>
          response(<int>[]),
      delay: (Duration duration) async {},
    );

    expect(await manager.updateBmp('X', Uint8List.fromList(<int>[1])), isFalse);
    expect(await manager.updateBmp('L', Uint8List(0)), isFalse);
    expect(
      await manager.updateBmp(
        'L',
        Uint8List(BmpUpdateManager.maximumImageBytes + 1),
      ),
      isFalse,
    );
    expect(sends, 0);
  });

  test('BMP transfer frames packets and validates both acknowledgements',
      () async {
    final sent = <Uint8List>[];
    final requested = <Uint8List>[];
    final manager = BmpUpdateManager(
      sendPacket: (Uint8List packet, String side) async {
        expect(side, 'L');
        sent.add(packet);
        return true;
      },
      request: (Uint8List packet, String side, int timeoutMs) async {
        expect(side, 'L');
        requested.add(packet);
        if (packet[0] == 0x20) {
          expect(timeoutMs, 3000);
          return response(<int>[0x20, 0xc9]);
        }
        expect(timeoutMs, 1000);
        return response(<int>[0x16, 0, 0, 0, 0, 0xc9]);
      },
      delay: (Duration duration) async {},
    );
    final image = Uint8List.fromList(
      List<int>.generate(200, (int index) => index & 0xff),
    );

    expect(await manager.updateBmp('L', image), isTrue);
    expect(sent, hasLength(2));
    expect(sent[0].sublist(0, 6), <int>[0x15, 0, 0, 0x1c, 0, 0]);
    expect(sent[0].length, 6 + BmpUpdateManager.packetPayloadLength);
    expect(sent[1].sublist(0, 2), <int>[0x15, 1]);
    expect(sent[1].length, 2 + 6);
    expect(requested.map((Uint8List packet) => packet[0]), <int>[0x20, 0x16]);
  });

  test('BMP transfer fails closed on an unaccepted packet', () async {
    var requests = 0;
    final manager = BmpUpdateManager(
      sendPacket: (Uint8List packet, String side) async => false,
      request: (Uint8List packet, String side, int timeoutMs) async {
        requests++;
        return response(<int>[]);
      },
      delay: (Duration duration) async {},
    );

    expect(
      await manager.updateBmp('R', Uint8List.fromList(<int>[1, 2, 3])),
      isFalse,
    );
    expect(requests, 0);
  });

  test('BMP transfer does not replay an indeterminate finish command',
      () async {
    var finishRequests = 0;
    final manager = BmpUpdateManager(
      sendPacket: (Uint8List packet, String side) async => true,
      request: (Uint8List packet, String side, int timeoutMs) async {
        if (packet[0] == 0x20) {
          finishRequests++;
          return BleReceive()
            ..isTimeout = true
            ..effectMayHaveOccurred = true;
        }
        return response(<int>[0x16, 0, 0, 0, 0, 0xc9]);
      },
      delay: (Duration duration) async {},
    );

    expect(
      await manager.updateBmp('L', Uint8List.fromList(<int>[1, 2, 3])),
      isFalse,
    );
    expect(finishRequests, 1);
  });

  test('BMP CRC acknowledgement requires the complete response shape', () {
    expect(
      BmpUpdateManager.isSuccessfulCrcResponse(
        response(<int>[0x16, 0, 0, 0, 0]),
      ),
      isFalse,
    );
    expect(
      BmpUpdateManager.isSuccessfulCrcResponse(
        response(<int>[0x16, 0, 0, 0, 0, 0xc9]),
      ),
      isTrue,
    );
  });
}
