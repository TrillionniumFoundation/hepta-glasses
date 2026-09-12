import 'dart:convert';
import 'dart:io';
import 'dart:math';
import 'dart:typed_data';

import 'package:demo_ai_even/runtime/packet_codec.dart';
import 'package:flutter_test/flutter_test.dart';

Uint8List _decodeHex(String value) {
  if (value.length.isOdd || !RegExp(r'^(?:[0-9a-f]{2})*$').hasMatch(value)) {
    throw FormatException('not canonical lowercase hex: $value');
  }
  return Uint8List.fromList(
    List<int>.generate(
      value.length ~/ 2,
      (int index) => int.parse(
        value.substring(index * 2, index * 2 + 2),
        radix: 16,
      ),
      growable: false,
    ),
  );
}

String _encodeHex(List<int> value) => value
    .map((int byte) => byte.toRadixString(16).padLeft(2, '0'))
    .join();

Map<String, Object?> _loadGoldenDocument() {
  final file = File('contracts/conformance/g1-packet-golden-v1.json');
  final decoded = jsonDecode(file.readAsStringSync());
  if (decoded is! Map<String, Object?>) {
    throw const FormatException('golden document must be an object');
  }
  const expectedKeys = <String>{
    'schema_version',
    'contract_id',
    'source_contract',
    'codec',
    'vectors',
    'negative_cases',
  };
  if (!decoded.keys.toSet().containsAll(expectedKeys) ||
      decoded.keys.length != expectedKeys.length) {
    throw const FormatException('golden document uses an open shape');
  }
  if (decoded['schema_version'] != 1 ||
      decoded['contract_id'] != 'hepta-g1-packet-golden-v1' ||
      decoded['source_contract'] != 'contracts/g1-ble-protocol-v1.json' ||
      decoded['codec'] != 'lib/runtime/packet_codec.dart') {
    throw const FormatException('golden document identity mismatch');
  }
  return decoded;
}

void main() {
  const codec = PacketCodec();
  late Map<String, Object?> document;

  setUpAll(() {
    document = _loadGoldenDocument();
  });

  test('Dart codec matches every shared G1 packet golden vector', () {
    final vectors = document['vectors'];
    expect(vectors, isA<List<Object?>>());
    final seen = <String>{};

    for (final raw in vectors! as List<Object?>) {
      expect(raw, isA<Map<String, Object?>>());
      final vector = raw! as Map<String, Object?>;
      expect(
        vector.keys.toSet(),
        <String>{
          'id',
          'command',
          'max_packet_bytes',
          'metadata',
          'payload_hex',
          'frames_hex',
          'reassembly_order',
        },
      );
      final id = vector['id'];
      expect(id, isA<String>());
      expect(
        RegExp(r'^[a-z0-9]+(?:-[a-z0-9]+)*$').hasMatch(id! as String),
        isTrue,
      );
      expect(seen.add(id), isTrue, reason: 'duplicate vector id: $id');

      final command = vector['command']! as int;
      final maxPacketBytes = vector['max_packet_bytes']! as int;
      final metadata = (vector['metadata']! as List<Object?>).cast<int>();
      final payload = _decodeHex(vector['payload_hex']! as String);
      final expectedFrames =
          (vector['frames_hex']! as List<Object?>).cast<String>();
      final order =
          (vector['reassembly_order']! as List<Object?>).cast<int>();

      final frames = codec.fragment(
        command: command,
        payload: payload,
        maxPacketBytes: maxPacketBytes,
        metadata: metadata,
      );
      expect(
        frames.map(_encodeHex).toList(growable: false),
        expectedFrames,
        reason: id,
      );
      expect(
        order.toList()..sort(),
        List<int>.generate(frames.length, (int index) => index),
        reason: '$id reassembly order must be a permutation',
      );
      final reordered =
          order.map((int index) => frames[index]).toList(growable: false);
      final rebuilt = codec.reassemble(
        reordered,
        expectedCommand: command,
        metadataLength: metadata.length,
      );
      expect(rebuilt, orderedEquals(payload), reason: id);
    }
  });

  test('seeded packet property sweep is bounded and round-trips', () {
    final random = Random(0x4845505441);
    for (var testCase = 0; testCase < 512; testCase++) {
      final metadata = List<int>.generate(
        random.nextInt(4),
        (int _) => random.nextInt(256),
        growable: false,
      );
      final minimum = 4 + metadata.length;
      final maxPacketBytes = minimum + random.nextInt(204 - minimum);
      final capacity = maxPacketBytes - 3 - metadata.length;
      final maximumPayload = min(capacity * 16, 4096);
      final payload = Uint8List.fromList(
        List<int>.generate(
          random.nextInt(maximumPayload + 1),
          (int _) => random.nextInt(256),
          growable: false,
        ),
      );
      final command = random.nextInt(256);
      final frames = codec.fragment(
        command: command,
        payload: payload,
        maxPacketBytes: maxPacketBytes,
        metadata: metadata,
      );
      final shuffled = frames.toList(growable: false)..shuffle(random);
      final rebuilt = codec.reassemble(
        shuffled,
        expectedCommand: command,
        metadataLength: metadata.length,
      );
      expect(rebuilt, orderedEquals(payload), reason: 'case $testCase');
      expect(frames.length, lessThanOrEqualTo(255));
      for (final frame in frames) {
        expect(frame.length, lessThanOrEqualTo(maxPacketBytes));
      }
    }
  });

  test('hostile frame mutations fail closed', () {
    final frames = codec.fragment(
      command: 0x4E,
      payload: Uint8List.fromList(List<int>.generate(17, (int i) => i)),
      maxPacketBytes: 10,
    );
    expect(frames.length, 3);

    final duplicate = <Uint8List>[
      frames[0],
      Uint8List.fromList(<int>[
        frames[1][0],
        frames[1][1],
        0,
        ...frames[1].sublist(3),
      ]),
      frames[2],
    ];
    expect(
      () => codec.reassemble(duplicate, expectedCommand: 0x4E),
      throwsFormatException,
    );

    expect(
      () => codec.reassemble(
        <Uint8List>[frames[0], frames[2]],
        expectedCommand: 0x4E,
      ),
      throwsFormatException,
    );
    expect(
      () => codec.reassemble(frames, expectedCommand: 0xFF),
      throwsFormatException,
    );

    final inconsistent = frames
        .map((Uint8List frame) => Uint8List.fromList(frame))
        .toList(growable: false);
    inconsistent[0][1] = 2;
    expect(
      () => codec.reassemble(inconsistent, expectedCommand: 0x4E),
      throwsFormatException,
    );
    expect(
      () => codec.reassemble(
        <Uint8List>[Uint8List.fromList(<int>[0x4E, 1])],
        expectedCommand: 0x4E,
      ),
      throwsFormatException,
    );
    expect(
      () => codec.reassemble(const <Uint8List>[]),
      throwsFormatException,
    );
    expect(
      () => codec.fragment(
        command: 0x15,
        payload: Uint8List(256),
        maxPacketBytes: 4,
      ),
      throwsStateError,
    );
  });

  test('negative-case registry is unique and complete', () {
    final negativeCases = (document['negative_cases']! as List<Object?>)
        .cast<Map<String, Object?>>();
    final ids = <String>{};
    final kinds = <String>{};
    for (final item in negativeCases) {
      expect(item.keys.toSet(), <String>{'id', 'kind'});
      expect(ids.add(item['id']! as String), isTrue);
      expect(kinds.add(item['kind']! as String), isTrue);
    }
    expect(
      kinds,
      <String>{
        'empty_frames',
        'duplicate_sequence',
        'missing_sequence',
        'wrong_command',
        'inconsistent_total',
        'short_header',
        'too_many_frames',
      },
    );
  });
}
