import 'dart:convert';
import 'dart:io';
import 'dart:math' as math;
import 'dart:typed_data';

import 'package:demo_ai_even/runtime/packet_codec.dart';
import 'package:flutter_test/flutter_test.dart';

Uint8List _hexBytes(String value) {
  if (value.length.isOdd || !RegExp(r'^[0-9a-f]*$').hasMatch(value)) {
    throw FormatException('invalid lowercase hexadecimal fixture: $value');
  }
  return Uint8List.fromList(<int>[
    for (var index = 0; index < value.length; index += 2)
      int.parse(value.substring(index, index + 2), radix: 16),
  ]);
}

String _hex(Uint8List value) =>
    value.map((int byte) => byte.toRadixString(16).padLeft(2, '0')).join();

void main() {
  final contractText = File(
    'contracts/conformance/g1-packet-v1.json',
  ).readAsStringSync();
  final contract = jsonDecode(contractText) as Map<String, Object?>;
  final vectors = contract['vectors']! as List<Object?>;

  test('Dart consumes every G1 packet golden vector', () {
    expect(contract['contract_id'], 'hepta-g1-packet-conformance-v1');
    expect(contract['schema_version'], 1);
    final identifiers = <String>{};
    const codec = PacketCodec();

    for (final raw in vectors) {
      final vector = Map<String, Object?>.from(raw! as Map);
      final identifier = vector['id']! as String;
      final metadata = _hexBytes(vector['metadata_hex']! as String);
      final payload = _hexBytes(vector['payload_hex']! as String);
      final rawFrames = vector['frames_hex']! as List<Object?>;
      final expectedFrames = rawFrames.cast<String>();
      final command = vector['command']! as int;
      final frames = codec.fragment(
        command: command,
        payload: payload,
        maxPacketBytes: vector['max_packet_bytes']! as int,
        metadata: metadata,
      );
      final encodedFrames = frames.map(_hex).toList(growable: false);

      expect(identifiers.add(identifier), isTrue, reason: identifier);
      expect(encodedFrames, expectedFrames, reason: identifier);
      expect(
        codec.reassemble(
          frames.reversed.toList(growable: false),
          expectedCommand: command,
          metadataLength: metadata.length,
        ),
        orderedEquals(payload),
        reason: identifier,
      );
    }
    expect(identifiers.length, greaterThanOrEqualTo(4));
  });

  test('metadata is a frame-set binding, not ignorable padding', () {
    const codec = PacketCodec();
    final frames = codec.fragment(
      command: 0x4e,
      payload: Uint8List.fromList(
        List<int>.generate(12, (int index) => index),
      ),
      maxPacketBytes: 8,
      metadata: const <int>[7, 9],
    );
    final malformed = frames
        .map((Uint8List frame) => Uint8List.fromList(frame))
        .toList(growable: false);
    malformed.last[3] ^= 1;

    expect(
      () => codec.reassemble(
        malformed,
        expectedCommand: 0x4e,
        metadataLength: 2,
      ),
      throwsFormatException,
    );
  });

  test('packet codec rejects every structural boundary', () {
    const codec = PacketCodec();
    expect(
      () => codec.fragment(command: -1, payload: Uint8List(0)),
      throwsRangeError,
    );
    expect(
      () => codec.fragment(
        command: 1,
        payload: Uint8List(0),
        metadata: const <int>[256],
      ),
      throwsRangeError,
    );
    expect(
      () => codec.fragment(
        command: 1,
        payload: Uint8List(0),
        maxPacketBytes: 3,
      ),
      throwsArgumentError,
    );
    expect(
      () => codec.fragment(
        command: 1,
        payload: Uint8List(256),
        maxPacketBytes: 4,
      ),
      throwsStateError,
    );
    expect(() => codec.reassemble(<Uint8List>[]), throwsFormatException);
    expect(
      () => codec.reassemble(<Uint8List>[Uint8List.fromList(<int>[1, 1])]),
      throwsFormatException,
    );
    expect(
      () => codec.reassemble(
        <Uint8List>[Uint8List.fromList(<int>[1, 1, 0])],
        expectedCommand: 2,
      ),
      throwsFormatException,
    );
    expect(
      () => codec.reassemble(
        <Uint8List>[Uint8List.fromList(<int>[1, 1, 0])],
        metadataLength: -1,
      ),
      throwsArgumentError,
    );
  });

  test('seeded packet parser fuzzing is deterministic and fail closed', () {
    const codec = PacketCodec();
    final random = math.Random(0x48455054);

    for (var iteration = 0; iteration < 500; iteration++) {
      final command = random.nextInt(256);
      final metadata = Uint8List.fromList(
        List<int>.generate(random.nextInt(5), (_) => random.nextInt(256)),
      );
      final headerBytes = 3 + metadata.length;
      final maxPacketBytes = headerBytes + 1 + random.nextInt(24);
      final chunkBytes = maxPacketBytes - headerBytes;
      final maximumPayload = math.min(1024, chunkBytes * 255);
      final payload = Uint8List.fromList(
        List<int>.generate(
          random.nextInt(maximumPayload + 1),
          (_) => random.nextInt(256),
        ),
      );
      final frames = codec.fragment(
        command: command,
        payload: payload,
        maxPacketBytes: maxPacketBytes,
        metadata: metadata,
      );
      final shuffled = frames.toList(growable: false)..shuffle(random);
      expect(
        codec.reassemble(
          shuffled,
          expectedCommand: command,
          metadataLength: metadata.length,
        ),
        orderedEquals(payload),
        reason: 'round-trip iteration $iteration',
      );

      final malformed = frames
          .map((Uint8List frame) => Uint8List.fromList(frame))
          .toList(growable: true);
      switch (iteration % 5) {
        case 0:
          malformed.first[1] = 0;
          break;
        case 1:
          malformed.first[2] = malformed.first[1];
          break;
        case 2:
          malformed.add(Uint8List.fromList(malformed.first));
          break;
        case 3:
          malformed.last[0] = (malformed.last[0] + 1) & 0xff;
          break;
        case 4:
          if (metadata.isNotEmpty && malformed.length > 1) {
            malformed.last[3] ^= 1;
          } else {
            final shortFrame = malformed.first.sublist(
              0,
              math.min(2, malformed.first.length),
            );
            malformed[0] = Uint8List.fromList(shortFrame);
          }
          break;
      }
      expect(
        () => codec.reassemble(
          malformed,
          expectedCommand: command,
          metadataLength: metadata.length,
        ),
        throwsFormatException,
        reason: 'malformed iteration $iteration',
      );
    }
  });
}
