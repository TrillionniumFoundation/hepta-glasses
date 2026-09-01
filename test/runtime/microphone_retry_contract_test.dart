import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('microphone retries only a proven pre-write-safe failure', () {
    final source = File('lib/services/evenai.dart').readAsStringSync();
    final start = source.indexOf('Future<bool> openEvenAIMic');
    final end = source.indexOf('Future<bool> sendEvenAIReply', start);

    expect(start, greaterThanOrEqualTo(0));
    expect(end, greaterThan(start));
    final method = source.substring(start, end);

    expect(method, contains('for (var attempt = 1; attempt <= 3; attempt++)'));
    expect(method, contains('if (outcome.committed)'));
    expect(method, contains('if (!outcome.retrySafe)'));
    expect(method, contains("'microphone_open_reconciliation_required'"));
    expect(method, contains('return false;'));
    expect(method, contains('Duration(seconds: 1)'));
    expect(
      method.indexOf('if (!outcome.retrySafe)'),
      lessThan(method.indexOf('Duration(seconds: 1)')),
    );
  });

  test('microphone attempt identity is carried into mutation authority', () {
    final assistant = File('lib/services/evenai.dart').readAsStringSync();
    final protocol = File('lib/services/proto.dart').readAsStringSync();
    final runtime = File('lib/runtime/hepta_runtime.dart').readAsStringSync();

    expect(assistant, contains('attempt: attempt'));
    expect(protocol, contains('attempt: attempt'));
    expect(runtime, contains("final attempt = request.arguments['attempt'];"));
    expect(runtime, contains("'attempt': attempt"));
  });
}
