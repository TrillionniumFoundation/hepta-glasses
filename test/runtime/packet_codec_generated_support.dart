part of 'packet_codec_test.dart';

final class _Lcg {
  _Lcg(this._state);

  int _state;

  int nextInt(int upperBound) {
    if (upperBound <= 0) {
      throw ArgumentError.value(upperBound, 'upperBound');
    }
    _state = (1664525 * _state + 1013904223) & 0xffffffff;
    return _state % upperBound;
  }

  Uint8List bytes(int length) => Uint8List.fromList(
        List<int>.generate(length, (_) => nextInt(256)),
      );
}

void _runGeneratedCase(
  PacketCodec codec,
  String family,
  _Lcg random,
) {
  switch (family) {
    case 'round-trip':
      final metadata = random.bytes(random.nextInt(4));
      final payload = random.bytes(random.nextInt(129));
      final maxPacketBytes = 4 + metadata.length + random.nextInt(20);
      final command = random.nextInt(256);
      final frames = codec.fragment(
        command: command,
        payload: payload,
        maxPacketBytes: maxPacketBytes,
        metadata: metadata,
      );
      expect(
        codec.reassemble(
          frames.reversed.toList(),
          expectedCommand: command,
          metadataLength: metadata.length,
        ),
        payload,
      );
      return;
    case 'zero-declared-frame-count':
      final metadata = random.bytes(random.nextInt(4));
      final frame = Uint8List.fromList(
        <int>[
          random.nextInt(256),
          0,
          0,
          ...metadata,
          random.nextInt(256),
        ],
      );
      _expectFormat(
        () => codec.reassemble(
          <Uint8List>[frame],
          metadataLength: metadata.length,
        ),
        'Frame count does not match header.',
      );
      return;
    case 'sequence-outside-range-same-cardinality':
      final total = 2 + random.nextInt(4);
      final metadata = random.bytes(random.nextInt(4));
      final frames = <Uint8List>[
        for (var sequence = 0; sequence < total - 1; sequence++)
          _frame(
            command: 78,
            total: total,
            sequence: sequence,
            metadata: metadata,
            payloadByte: random.nextInt(256),
          ),
        _frame(
          command: 78,
          total: total,
          sequence: total,
          metadata: metadata,
          payloadByte: random.nextInt(256),
        ),
      ];
      expect(frames.length, total);
      _expectFormat(
        () => codec.reassemble(
          frames,
          metadataLength: metadata.length,
        ),
        'Frame sequence is outside declared range.',
      );
      return;
    case 'duplicate-sequence-same-cardinality':
      final total = 3 + random.nextInt(3);
      final metadata = random.bytes(random.nextInt(4));
      final frames = <Uint8List>[
        for (var sequence = 0; sequence < total - 1; sequence++)
          _frame(
            command: 78,
            total: total,
            sequence: sequence,
            metadata: metadata,
            payloadByte: random.nextInt(256),
          ),
        _frame(
          command: 78,
          total: total,
          sequence: total - 2,
          metadata: metadata,
          payloadByte: random.nextInt(256),
        ),
      ];
      expect(frames.length, total);
      _expectFormat(
        () => codec.reassemble(
          frames,
          metadataLength: metadata.length,
        ),
        'Duplicate frame sequence.',
      );
      return;
    case 'metadata-drift':
      final metadata = random.bytes(1 + random.nextInt(3));
      final changed = Uint8List.fromList(metadata)..[0] = metadata[0] ^ 0x01;
      final frames = <Uint8List>[
        _frame(
          command: 78,
          total: 2,
          sequence: 0,
          metadata: metadata,
          payloadByte: random.nextInt(256),
        ),
        _frame(
          command: 78,
          total: 2,
          sequence: 1,
          metadata: changed,
          payloadByte: random.nextInt(256),
        ),
      ];
      _expectFormat(
        () => codec.reassemble(
          frames,
          metadataLength: metadata.length,
        ),
        'Inconsistent frame metadata.',
      );
      return;
    case 'command-drift':
      final frames = <Uint8List>[
        _frame(
          command: 78,
          total: 2,
          sequence: 0,
          metadata: Uint8List(0),
          payloadByte: random.nextInt(256),
        ),
        _frame(
          command: 79,
          total: 2,
          sequence: 1,
          metadata: Uint8List(0),
          payloadByte: random.nextInt(256),
        ),
      ];
      _expectFormat(
        () => codec.reassemble(frames),
        'Inconsistent frame header.',
      );
      return;
    case 'total-drift':
      final frames = <Uint8List>[
        _frame(
          command: 78,
          total: 2,
          sequence: 0,
          metadata: Uint8List(0),
          payloadByte: random.nextInt(256),
        ),
        _frame(
          command: 78,
          total: 3,
          sequence: 1,
          metadata: Uint8List(0),
          payloadByte: random.nextInt(256),
        ),
      ];
      _expectFormat(
        () => codec.reassemble(frames),
        'Inconsistent frame header.',
      );
      return;
    default:
      throw FormatException('Unknown generated family: $family');
  }
}

Uint8List _frame({
  required int command,
  required int total,
  required int sequence,
  required Uint8List metadata,
  required int payloadByte,
}) =>
    Uint8List.fromList(
      <int>[command, total, sequence, ...metadata, payloadByte],
    );

void _expectFormat(void Function() operation, String message) {
  expect(
    operation,
    throwsA(
      isA<FormatException>().having(
        (error) => error.message,
        'message',
        message,
      ),
    ),
  );
}

String _mutantHarness(String packetCodecFile) => '''
import 'dart:io';
import 'dart:typed_data';

import '$packetCodecFile';

void main() {
  try {
    const PacketCodec().reassemble(
      <Uint8List>[
        Uint8List.fromList(const <int>[78, 3, 0, 170]),
        Uint8List.fromList(const <int>[78, 3, 1, 187]),
        Uint8List.fromList(const <int>[78, 3, 1, 204]),
      ],
    );
  } on FormatException catch (error) {
    stderr.writeln(error.message);
    if (error.message == 'Duplicate frame sequence.') {
      exit(0);
    }
    exit(23);
  }
  stderr.writeln('mutant accepted a duplicate sequence');
  exit(24);
}
''';
