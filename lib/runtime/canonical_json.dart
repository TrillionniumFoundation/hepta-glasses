import 'dart:convert';

import 'package:crypto/crypto.dart';

Object? _normalizeJson(Object? value) {
  if (value is Map) {
    final keys = <String>[];
    for (final key in value.keys) {
      if (key is! String) {
        throw ArgumentError.value(
          value,
          'value',
          'contains a non-string JSON object key',
        );
      }
      keys.add(key);
    }
    keys.sort();
    return <String, Object?>{
      for (final key in keys) key: _normalizeJson(value[key]),
    };
  }
  if (value is Iterable) {
    return value.map(_normalizeJson).toList(growable: false);
  }
  if (value is num) {
    if (!value.isFinite) {
      throw ArgumentError.value(
        value,
        'value',
        'contains a non-finite JSON number',
      );
    }
    return value;
  }
  if (value == null || value is String || value is bool) {
    return value;
  }
  throw ArgumentError.value(value, 'value', 'is not JSON serializable');
}

String canonicalJson(Object? value) => jsonEncode(_normalizeJson(value));

String sha256CanonicalJson(Object? value) =>
    sha256.convert(utf8.encode(canonicalJson(value))).toString();
