import 'dart:convert';

import 'package:hepta_glasses/runtime/strict_json.dart';
import 'package:flutter_test/flutter_test.dart';

Object? decode(
  String source, {
  int maxBytes = 4096,
  int maxDepth = 32,
  int maxTokens = 4096,
}) =>
    decodeStrictJsonBytes(
      utf8.encode(source),
      maxBytes: maxBytes,
      maxDepth: maxDepth,
      maxTokens: maxTokens,
    );

void main() {
  test('strict decoder preserves every JSON value class', () {
    final value = decode(
      r'{"array":[true,false,null,-7,1.25,1e2],"object":{"text":"眼镜","emoji":"🧠"},"escaped":"a\nb\t\\"}',
    );

    expect(
      value,
      <String, Object?>{
        'array': <Object?>[true, false, null, -7, 1.25, 100.0],
        'object': <String, Object?>{
          'text': '眼镜',
          'emoji': '🧠',
        },
        'escaped': 'a\nb\t\\',
      },
    );
  });

  test('duplicate members at every depth are rejected', () {
    const cases = <String>[
      '{"id":1,"id":2}',
      '{"outer":{"id":1,"id":2}}',
      '[{"id":1,"id":2}]',
      '{"\\u0069d":1,"id":2}',
    ];
    for (final source in cases) {
      expect(
        () => decode(source),
        throwsA(
          isA<FormatException>().having(
            (error) => error.message,
            'message',
            contains('Duplicate JSON object member'),
          ),
        ),
        reason: source,
      );
    }
  });

  test('invalid UTF-8 BOM empty and byte limits fail before parsing', () {
    final cases = <List<int>>[
      const <int>[],
      const <int>[0xff],
      const <int>[0xef, 0xbb, 0xbf, 0x7b, 0x7d],
    ];
    for (final bytes in cases) {
      expect(
        () => decodeStrictJsonBytes(bytes, maxBytes: 16),
        throwsFormatException,
      );
    }
    expect(
      () => decodeStrictJsonBytes(
        utf8.encode('{"value":1}'),
        maxBytes: 4,
      ),
      throwsFormatException,
    );
  });

  test('number grammar is strict and finite', () {
    const invalid = <String>[
      '01',
      '-01',
      '1.',
      '1e',
      '1e+',
      '--1',
      '+1',
      'NaN',
      'Infinity',
      '-Infinity',
      '999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999',
      '1e9999',
    ];
    for (final source in invalid) {
      expect(
        () => decode(source),
        throwsFormatException,
        reason: source,
      );
    }
  });

  test('string escapes and surrogate pairs are closed', () {
    expect(decode('"\\uD83E\\uDDE0"'), '🧠');
    expect(decode('"\\u0041"'), 'A');

    const invalid = <String>[
      '"unterminated',
      '"\\x20"',
      '"\\u12"',
      '"\\uD83E"',
      '"\\uDDE0"',
      '"\\uD83E\\u0041"',
      '"\n"',
    ];
    for (final source in invalid) {
      expect(
        () => decode(source),
        throwsFormatException,
        reason: source,
      );
    }
  });

  test('trailing data and container punctuation drift are rejected', () {
    const invalid = <String>[
      '{}{}',
      '[] true',
      '{"a":1,}',
      '[1,]',
      '{"a" 1}',
      '{"a":}',
      '{1:2}',
    ];
    for (final source in invalid) {
      expect(
        () => decode(source),
        throwsFormatException,
        reason: source,
      );
    }
  });

  test('depth and token limits are enforced', () {
    expect(
      () => decode(
        '[[[0]]]',
        maxDepth: 2,
      ),
      throwsFormatException,
    );
    expect(
      () => decode(
        '[0,1,2]',
        maxTokens: 3,
      ),
      throwsFormatException,
    );
    expect(
      () => decode('{}', maxBytes: 0),
      throwsArgumentError,
    );
    expect(
      () => decode('{}', maxDepth: 0),
      throwsArgumentError,
    );
    expect(
      () => decode('{}', maxTokens: 0),
      throwsArgumentError,
    );
  });
}
