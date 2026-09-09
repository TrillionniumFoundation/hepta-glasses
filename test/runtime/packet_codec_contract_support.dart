part of 'packet_codec_test.dart';

final class _PositiveVector {
  const _PositiveVector({
    required this.id,
    required this.command,
    required this.maxPacketBytes,
    required this.metadata,
    required this.payload,
    required this.frames,
  });

  final String id;
  final int command;
  final int maxPacketBytes;
  final Uint8List metadata;
  final Uint8List payload;
  final List<Uint8List> frames;
}

final class _NegativeVector {
  const _NegativeVector({
    required this.id,
    required this.frames,
    required this.metadataLength,
    required this.expectedCommand,
    required this.expectedError,
  });

  final String id;
  final List<Uint8List> frames;
  final int metadataLength;
  final int? expectedCommand;
  final String expectedError;
}

final class _GeneratedFamily {
  const _GeneratedFamily({
    required this.id,
    required this.seed,
    required this.cases,
  });

  final String id;
  final int seed;
  final int cases;
}

final class _PacketContract {
  const _PacketContract({
    required this.vectors,
    required this.negativeVectors,
    required this.generatedFamilies,
  });

  final List<_PositiveVector> vectors;
  final List<_NegativeVector> negativeVectors;
  final List<_GeneratedFamily> generatedFamilies;
}

_PacketContract _loadContract() {
  final bytes = File(
    'contracts/conformance/g1-packet-v1.json',
  ).readAsBytesSync();
  final root = _closedObject(
    decodeStrictJsonBytes(bytes, maxBytes: 256 * 1024),
    <String>{
      'contract_id',
      'schema_version',
      'header',
      'vectors',
      'negative_vectors',
      'generated_families',
    },
    'contract',
  );
  if (root['contract_id'] != 'hepta-g1-packet-conformance-v2' ||
      root['schema_version'] != 2) {
    throw const FormatException('Unexpected packet contract identity.');
  }

  final header = _closedObject(
    root['header'],
    <String>{
      'command_offset',
      'frame_count_offset',
      'sequence_offset',
      'fixed_bytes',
    },
    'header',
  );
  const expectedHeader = <String, int>{
    'command_offset': 0,
    'frame_count_offset': 1,
    'sequence_offset': 2,
    'fixed_bytes': 3,
  };
  if (header.length != expectedHeader.length ||
      !expectedHeader.entries.every(
        (entry) => header[entry.key] == entry.value,
      )) {
    throw const FormatException('Packet header contract drift.');
  }

  final vectors = _list(root['vectors'], 'vectors')
      .map(_positiveVector)
      .toList(growable: false);
  final negativeVectors = _list(
    root['negative_vectors'],
    'negative_vectors',
  ).map(_negativeVector).toList(growable: false);
  final generatedFamilies = _list(
    root['generated_families'],
    'generated_families',
  ).map(_generatedFamily).toList(growable: false);

  _requireExactIds(
    vectors.map((vector) => vector.id),
    const <String>[
      'empty-payload',
      'single-frame-with-metadata',
      'five-binary-frames',
      'utf8-is-opaque-bytes',
    ],
    'positive vectors',
  );
  _requireExactIds(
    negativeVectors.map((vector) => vector.id),
    const <String>[
      'empty-frame-set',
      'short-first-frame',
      'zero-declared-frame-count',
      'declared-count-does-not-match-cardinality',
      'expected-command-mismatch',
      'inconsistent-frame-command',
      'inconsistent-frame-total',
      'inconsistent-metadata',
      'sequence-outside-range-same-cardinality',
      'duplicate-sequence-same-cardinality',
    ],
    'negative vectors',
  );
  _requireExactIds(
    generatedFamilies.map((family) => family.id),
    const <String>[
      'round-trip',
      'zero-declared-frame-count',
      'sequence-outside-range-same-cardinality',
      'duplicate-sequence-same-cardinality',
      'metadata-drift',
      'command-drift',
      'total-drift',
    ],
    'generated families',
  );
  const expectedGenerated = <String, (int, int)>{
    'round-trip': (12648430, 128),
    'zero-declared-frame-count': (60417409, 64),
    'sequence-outside-range-same-cardinality': (2882343476, 64),
    'duplicate-sequence-same-cardinality': (3735928559, 64),
    'metadata-drift': (195936478, 64),
    'command-drift': (4277009102, 64),
    'total-drift': (305419896, 64),
  };
  for (final family in generatedFamilies) {
    final expected = expectedGenerated[family.id];
    if (expected == null ||
        family.seed != expected.$1 ||
        family.cases != expected.$2) {
      throw FormatException(
        'Generated family drift: ${family.id}',
      );
    }
  }

  return _PacketContract(
    vectors: vectors,
    negativeVectors: negativeVectors,
    generatedFamilies: generatedFamilies,
  );
}

_PositiveVector _positiveVector(Object? value) {
  final object = _closedObject(
    value,
    <String>{
      'id',
      'command',
      'max_packet_bytes',
      'metadata_hex',
      'payload_hex',
      'frames_hex',
    },
    'positive vector',
  );
  final id = _string(object['id'], 'positive vector id');
  final command = _boundedInt(object['command'], 'command', 0, 255);
  final maxPacketBytes = _boundedInt(
    object['max_packet_bytes'],
    'max_packet_bytes',
    4,
    255,
  );
  final metadata = _hex(_text(object['metadata_hex'], 'metadata_hex'));
  final payload = _hex(_text(object['payload_hex'], 'payload_hex'));
  final frames = _stringList(object['frames_hex'], 'frames_hex')
      .map(_hex)
      .toList(growable: false);
  if (frames.isEmpty || maxPacketBytes <= 3 + metadata.length) {
    throw FormatException('Invalid positive vector: $id');
  }
  return _PositiveVector(
    id: id,
    command: command,
    maxPacketBytes: maxPacketBytes,
    metadata: metadata,
    payload: payload,
    frames: frames,
  );
}

_NegativeVector _negativeVector(Object? value) {
  final object = _closedObject(
    value,
    <String>{
      'id',
      'frames_hex',
      'metadata_length',
      'expected_command',
      'expected_error',
    },
    'negative vector',
  );
  final expectedCommand = object['expected_command'];
  if (expectedCommand != null) {
    _boundedInt(expectedCommand, 'expected_command', 0, 255);
  }
  return _NegativeVector(
    id: _string(object['id'], 'negative vector id'),
    frames: _stringList(
      object['frames_hex'],
      'negative frames_hex',
      allowEmpty: true,
    ).map(_hex).toList(growable: false),
    metadataLength: _boundedInt(
      object['metadata_length'],
      'metadata_length',
      0,
      252,
    ),
    expectedCommand: expectedCommand as int?,
    expectedError: _string(object['expected_error'], 'expected_error'),
  );
}

_GeneratedFamily _generatedFamily(Object? value) {
  final object = _closedObject(
    value,
    <String>{'id', 'seed', 'cases'},
    'generated family',
  );
  return _GeneratedFamily(
    id: _string(object['id'], 'generated family id'),
    seed: _boundedInt(object['seed'], 'seed', 0, 0xffffffff),
    cases: _boundedInt(object['cases'], 'cases', 1, 10000),
  );
}

Map<String, Object?> _closedObject(
  Object? value,
  Set<String> fields,
  String label,
) {
  if (value is! Map<String, Object?> ||
      value.length != fields.length ||
      !value.keys.every(fields.contains)) {
    throw FormatException('$label must use the exact closed shape.');
  }
  return value;
}

List<Object?> _list(Object? value, String label) {
  if (value is! List<Object?>) {
    throw FormatException('$label must be an array.');
  }
  return value;
}

List<String> _stringList(
  Object? value,
  String label, {
  bool allowEmpty = false,
}) {
  final list = _list(value, label);
  if ((!allowEmpty && list.isEmpty) || list.any((item) => item is! String)) {
    throw FormatException('$label must be a string array.');
  }
  return list.cast<String>();
}

String _text(Object? value, String label) {
  if (value is! String) {
    throw FormatException('$label must be a string.');
  }
  return value;
}

String _string(Object? value, String label) {
  final text = _text(value, label);
  if (text.isEmpty) {
    throw FormatException('$label must be a non-empty string.');
  }
  return text;
}

int _boundedInt(
  Object? value,
  String label,
  int minimum,
  int maximum,
) {
  if (value is! int || value < minimum || value > maximum) {
    throw FormatException('$label is outside its integer range.');
  }
  return value;
}

void _requireExactIds(
  Iterable<String> actual,
  List<String> expected,
  String label,
) {
  final values = actual.toList(growable: false);
  if (values.length != values.toSet().length ||
      values.length != expected.length ||
      !List<bool>.generate(
        values.length,
        (index) => values[index] == expected[index],
      ).every((item) => item)) {
    throw FormatException('$label identity/order drift.');
  }
}

Uint8List _hex(String value) {
  if (value.length.isOdd || !RegExp(r'^[0-9a-f]*$').hasMatch(value)) {
    throw const FormatException('Invalid lowercase hexadecimal fixture.');
  }
  return Uint8List.fromList(
    <int>[
      for (var index = 0; index < value.length; index += 2)
        int.parse(value.substring(index, index + 2), radix: 16),
    ],
  );
}

String _toHex(Uint8List bytes) =>
    bytes.map((value) => value.toRadixString(16).padLeft(2, '0')).join();
