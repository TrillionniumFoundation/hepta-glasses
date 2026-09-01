import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('heartbeat retry loop is gated by retrySafe', () {
    final source = File('lib/ble_manager.dart').readAsStringSync();
    final start = source.indexOf('Future<void> _sendHeartbeat()');
    final end = source.indexOf('void _onGlassesConnecting', start);

    expect(start, greaterThanOrEqualTo(0));
    expect(end, greaterThan(start));
    final method = source.substring(start, end);

    expect(
      method,
      contains('var outcome = await Proto.sendHeartBeatEffect();'),
    );
    expect(method, contains('outcome.retrySafe &&'));
    expect(method, contains('attempt < 2'));
    expect(method, contains('if (!outcome.committed)'));
    expect(
      RegExp(r'Proto[.]sendHeartBeatEffect[(][)]').allMatches(method),
      hasLength(2),
    );
  });

  test('heartbeat outcome distinguishes uncertain and safe failure', () {
    final protocol = File('lib/services/proto.dart').readAsStringSync();
    final start = protocol.indexOf(
      'static Future<DeviceEffectResult> sendHeartBeatEffect',
    );
    final end = protocol.indexOf('static bool _isHeartbeatAck', start);

    expect(start, greaterThanOrEqualTo(0));
    expect(end, greaterThan(start));
    final method = protocol.substring(start, end);

    expect(method, contains('_sendSequenceToBothLegs'));
    expect(method, contains("operation: 'heartbeat:"));
    expect(protocol, contains('effectMayHaveOccurred'));
    expect(protocol, contains('negative_or_malformed_ack_after_write'));
  });
}
