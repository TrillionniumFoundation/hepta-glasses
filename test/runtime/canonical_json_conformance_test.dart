import 'dart:convert';
import 'dart:io';

import 'package:demo_ai_even/runtime/canonical_json.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  final contract = jsonDecode(
    File(
      'contracts/conformance/canonical-json-v1.json',
    ).readAsStringSync(),
  ) as Map<String, Object?>;
  final vectors = contract['vectors']! as List<Object?>;

  test('Dart consumes every canonical JSON conformance vector', () {
    expect(
      contract['contract_id'],
      'hepta-canonical-json-conformance-v1',
    );
    final identifiers = <String>{};
    for (final raw in vectors) {
      final vector = raw! as Map<String, Object?>;
      final identifier = vector['id']! as String;
      expect(identifiers.add(identifier), isTrue);
      expect(canonicalJson(vector['value']), vector['canonical']);
      expect(sha256CanonicalJson(vector['value']), vector['sha256']);
    }
    expect(identifiers.length, greaterThanOrEqualTo(6));
  });

  test('canonical JSON rejects non-string map keys', () {
    expect(
      () => canonicalJson(<Object?, Object?>{1: 'not-authority'}),
      throwsArgumentError,
    );
  });

  test('canonical JSON rejects non-finite numbers', () {
    for (final value in <double>[
      double.nan,
      double.infinity,
      double.negativeInfinity,
    ]) {
      expect(
        () => canonicalJson(<String, Object?>{'value': value}),
        throwsArgumentError,
      );
    }
  });
}
