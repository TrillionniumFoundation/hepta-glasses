import 'dart:convert';
import 'dart:typed_data';

import 'package:demo_ai_even/runtime/packet_codec.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('packet codec round-trips bounded frames', () {
    const codec = PacketCodec();
    final payload = Uint8List.fromList(utf8.encode('hepta glasses runtime'));
    final frames = codec.fragment(
      command: 0x4e,
      payload: payload,
      maxPacketBytes: 10,
      metadata: const <int>[7],
    );

    expect(frames, isNotEmpty);
    expect(frames.every((Uint8List frame) => frame.length <= 10), isTrue);
    expect(
      codec.reassemble(
        frames.reversed.toList(),
        expectedCommand: 0x4e,
        metadataLength: 1,
      ),
      orderedEquals(payload),
    );
  });

  test('packet codec rejects duplicate sequence', () {
    const codec = PacketCodec();
    final frames = codec.fragment(
      command: 1,
      payload: Uint8List.fromList(List<int>.generate(20, (int index) => index)),
      maxPacketBytes: 8,
    );
    final malformed = <Uint8List>[...frames]..[1] = frames.first;
    expect(
      () => codec.reassemble(malformed, expectedCommand: 1),
      throwsFormatException,
    );
  });
}
