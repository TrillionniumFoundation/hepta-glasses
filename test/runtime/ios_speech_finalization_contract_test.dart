import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('iOS speech waits for framework final and discards bounded partials',
      () {
    final source =
        File('ios/Runner/SpeechStreamRecognizer.swift').readAsStringSync();

    expect(source, contains('result.isFinal'));
    expect(source, contains('request?.endAudio()'));
    expect(source, contains('"framework_final"'));
    expect(source, contains('"timeout_partial"'));
    expect(source, contains('"framework_error_partial"'));
    expect(source,
        contains('let emittedTranscript = frameworkFinal ? transcript : ""'));
    expect(source, contains('"partial_discarded": !frameworkFinal'));
  });
}
