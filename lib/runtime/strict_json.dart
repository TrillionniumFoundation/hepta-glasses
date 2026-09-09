import 'dart:convert';

/// Decodes one bounded UTF-8 JSON value without losing duplicate object keys.
///
/// Dart's standard JSON decoder applies last-member-wins semantics. Authority
/// responses cannot use it at the wire boundary because a conflicting duplicate
/// member would disappear before policy validation sees the object.
Object? decodeStrictJsonBytes(
  List<int> bytes, {
  required int maxBytes,
  int maxDepth = 32,
  int maxTokens = 4096,
}) {
  if (maxBytes < 1 || maxDepth < 1 || maxTokens < 1) {
    throw ArgumentError('Strict JSON limits must be positive.');
  }
  if (bytes.isEmpty) {
    throw const FormatException('JSON body is empty.');
  }
  if (bytes.length > maxBytes) {
    throw const FormatException('JSON body exceeds the byte limit.');
  }
  if (bytes.length >= 3 &&
      bytes[0] == 0xef &&
      bytes[1] == 0xbb &&
      bytes[2] == 0xbf) {
    throw const FormatException('JSON body must not contain a UTF-8 BOM.');
  }

  late final String source;
  try {
    source = utf8.decode(bytes, allowMalformed: false);
  } on FormatException {
    throw const FormatException('JSON body is not valid UTF-8.');
  }
  if (source.isNotEmpty && source.codeUnitAt(0) == 0xfeff) {
    throw const FormatException('JSON body must not contain a UTF-8 BOM.');
  }
  return _StrictJsonParser(
    source,
    maxDepth: maxDepth,
    maxTokens: maxTokens,
  ).parse();
}

final class _StrictJsonParser {
  _StrictJsonParser(
    this.source, {
    required this.maxDepth,
    required this.maxTokens,
  });

  final String source;
  final int maxDepth;
  final int maxTokens;

  int _index = 0;
  int _depth = 0;
  int _tokens = 0;

  Object? parse() {
    _skipWhitespace();
    final value = _parseValue();
    _skipWhitespace();
    if (_index != source.length) {
      throw _error('Trailing data after the JSON value.');
    }
    return value;
  }

  Object? _parseValue() {
    _countToken();
    if (_index >= source.length) {
      throw _error('Unexpected end of JSON input.');
    }
    switch (source.codeUnitAt(_index)) {
      case 0x7b:
        return _parseObject();
      case 0x5b:
        return _parseArray();
      case 0x22:
        return _parseString();
      case 0x74:
        _expectKeyword('true');
        return true;
      case 0x66:
        _expectKeyword('false');
        return false;
      case 0x6e:
        _expectKeyword('null');
        return null;
      default:
        return _parseNumber();
    }
  }

  Map<String, Object?> _parseObject() {
    _enterContainer();
    try {
      _expectCodeUnit(0x7b);
      _skipWhitespace();
      final result = <String, Object?>{};
      if (_consumeCodeUnit(0x7d)) {
        return result;
      }

      while (true) {
        if (_index >= source.length || source.codeUnitAt(_index) != 0x22) {
          throw _error('JSON object key must be a string.');
        }
        final key = _parseString();
        if (result.containsKey(key)) {
          throw _error('Duplicate JSON object member: $key');
        }
        _skipWhitespace();
        _expectCodeUnit(0x3a);
        _skipWhitespace();
        result[key] = _parseValue();
        _skipWhitespace();
        if (_consumeCodeUnit(0x7d)) {
          return result;
        }
        _expectCodeUnit(0x2c);
        _skipWhitespace();
      }
    } finally {
      _depth -= 1;
    }
  }

  List<Object?> _parseArray() {
    _enterContainer();
    try {
      _expectCodeUnit(0x5b);
      _skipWhitespace();
      final result = <Object?>[];
      if (_consumeCodeUnit(0x5d)) {
        return result;
      }

      while (true) {
        result.add(_parseValue());
        _skipWhitespace();
        if (_consumeCodeUnit(0x5d)) {
          return result;
        }
        _expectCodeUnit(0x2c);
        _skipWhitespace();
      }
    } finally {
      _depth -= 1;
    }
  }

  String _parseString() {
    _expectCodeUnit(0x22);
    final buffer = StringBuffer();
    while (_index < source.length) {
      final codeUnit = source.codeUnitAt(_index);
      _index += 1;

      if (codeUnit == 0x22) {
        return buffer.toString();
      }
      if (codeUnit < 0x20) {
        throw _error('Unescaped control character in JSON string.');
      }
      if (codeUnit == 0x5c) {
        _parseEscape(buffer);
        continue;
      }
      if (_isHighSurrogate(codeUnit)) {
        if (_index >= source.length) {
          throw _error('Unpaired high surrogate in JSON string.');
        }
        final low = source.codeUnitAt(_index);
        if (!_isLowSurrogate(low)) {
          throw _error('Unpaired high surrogate in JSON string.');
        }
        _index += 1;
        buffer
          ..writeCharCode(codeUnit)
          ..writeCharCode(low);
        continue;
      }
      if (_isLowSurrogate(codeUnit)) {
        throw _error('Unpaired low surrogate in JSON string.');
      }
      buffer.writeCharCode(codeUnit);
    }
    throw _error('Unterminated JSON string.');
  }

  void _parseEscape(StringBuffer buffer) {
    if (_index >= source.length) {
      throw _error('Unterminated JSON escape.');
    }
    final escape = source.codeUnitAt(_index);
    _index += 1;
    switch (escape) {
      case 0x22:
      case 0x2f:
      case 0x5c:
        buffer.writeCharCode(escape);
        return;
      case 0x62:
        buffer.writeCharCode(0x08);
        return;
      case 0x66:
        buffer.writeCharCode(0x0c);
        return;
      case 0x6e:
        buffer.writeCharCode(0x0a);
        return;
      case 0x72:
        buffer.writeCharCode(0x0d);
        return;
      case 0x74:
        buffer.writeCharCode(0x09);
        return;
      case 0x75:
        final first = _parseHexQuad();
        if (_isHighSurrogate(first)) {
          if (_index + 1 >= source.length ||
              source.codeUnitAt(_index) != 0x5c ||
              source.codeUnitAt(_index + 1) != 0x75) {
            throw _error('Escaped high surrogate lacks a low surrogate.');
          }
          _index += 2;
          final second = _parseHexQuad();
          if (!_isLowSurrogate(second)) {
            throw _error('Escaped high surrogate lacks a low surrogate.');
          }
          buffer
            ..writeCharCode(first)
            ..writeCharCode(second);
          return;
        }
        if (_isLowSurrogate(first)) {
          throw _error('Escaped low surrogate lacks a high surrogate.');
        }
        buffer.writeCharCode(first);
        return;
      default:
        throw _error('Unsupported JSON escape.');
    }
  }

  int _parseHexQuad() {
    if (_index + 4 > source.length) {
      throw _error('Incomplete JSON Unicode escape.');
    }
    var value = 0;
    for (var offset = 0; offset < 4; offset++) {
      final digit = source.codeUnitAt(_index + offset);
      final nibble = switch (digit) {
        >= 0x30 && <= 0x39 => digit - 0x30,
        >= 0x41 && <= 0x46 => digit - 0x41 + 10,
        >= 0x61 && <= 0x66 => digit - 0x61 + 10,
        _ => -1,
      };
      if (nibble < 0) {
        throw _error('Invalid JSON Unicode escape.');
      }
      value = (value << 4) | nibble;
    }
    _index += 4;
    return value;
  }

  num _parseNumber() {
    final start = _index;
    if (_consumeCodeUnit(0x2d) && _index >= source.length) {
      throw _error('Incomplete JSON number.');
    }

    if (_consumeCodeUnit(0x30)) {
      if (_index < source.length && _isDigit(source.codeUnitAt(_index))) {
        throw _error('JSON number has a leading zero.');
      }
    } else {
      _consumeDigits(requireOne: true);
    }

    var floatingPoint = false;
    if (_consumeCodeUnit(0x2e)) {
      floatingPoint = true;
      _consumeDigits(requireOne: true);
    }
    if (_index < source.length) {
      final exponent = source.codeUnitAt(_index);
      if (exponent == 0x65 || exponent == 0x45) {
        floatingPoint = true;
        _index += 1;
        if (_index < source.length) {
          final sign = source.codeUnitAt(_index);
          if (sign == 0x2b || sign == 0x2d) {
            _index += 1;
          }
        }
        _consumeDigits(requireOne: true);
      }
    }

    final literal = source.substring(start, _index);
    if (literal.length > 128) {
      throw _error('JSON number literal is too long.');
    }
    if (!floatingPoint) {
      final integer = int.tryParse(literal);
      if (integer == null) {
        throw _error('JSON integer is outside the supported range.');
      }
      return integer;
    }
    final number = double.tryParse(literal);
    if (number == null || !number.isFinite) {
      throw _error('JSON number must be finite.');
    }
    return number;
  }

  void _consumeDigits({required bool requireOne}) {
    final start = _index;
    while (_index < source.length && _isDigit(source.codeUnitAt(_index))) {
      _index += 1;
    }
    if (requireOne && start == _index) {
      throw _error('JSON number requires a digit.');
    }
  }

  void _expectKeyword(String keyword) {
    if (!source.startsWith(keyword, _index)) {
      throw _error('Invalid JSON literal.');
    }
    _index += keyword.length;
  }

  void _enterContainer() {
    if (_depth >= maxDepth) {
      throw _error('JSON nesting exceeds the depth limit.');
    }
    _depth += 1;
  }

  void _countToken() {
    _tokens += 1;
    if (_tokens > maxTokens) {
      throw _error('JSON token count exceeds the limit.');
    }
  }

  void _skipWhitespace() {
    while (_index < source.length) {
      final codeUnit = source.codeUnitAt(_index);
      if (codeUnit != 0x20 &&
          codeUnit != 0x09 &&
          codeUnit != 0x0a &&
          codeUnit != 0x0d) {
        return;
      }
      _index += 1;
    }
  }

  bool _consumeCodeUnit(int expected) {
    if (_index < source.length && source.codeUnitAt(_index) == expected) {
      _index += 1;
      return true;
    }
    return false;
  }

  void _expectCodeUnit(int expected) {
    if (!_consumeCodeUnit(expected)) {
      throw _error(
        'Expected ${String.fromCharCode(expected)} in JSON input.',
      );
    }
  }

  FormatException _error(String message) =>
      FormatException(message, source, _index);

  static bool _isDigit(int codeUnit) => codeUnit >= 0x30 && codeUnit <= 0x39;

  static bool _isHighSurrogate(int codeUnit) =>
      codeUnit >= 0xd800 && codeUnit <= 0xdbff;

  static bool _isLowSurrogate(int codeUnit) =>
      codeUnit >= 0xdc00 && codeUnit <= 0xdfff;
}
