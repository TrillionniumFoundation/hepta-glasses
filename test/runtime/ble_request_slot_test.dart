import 'dart:async';

import 'package:demo_ai_even/runtime/ble_request_slot.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  const key = BleRequestKey(generation: 7, side: 'L', command: 0x25);

  test('one exact BLE key has one response owner', () {
    final registry = BleRequestRegistry<int>();
    final first = BleRequestSlot<int>(
      completer: Completer<int>(),
      generation: 7,
    );
    final second = BleRequestSlot<int>(
      completer: Completer<int>(),
      generation: 7,
    );

    expect(registry.reserve(key, first), isTrue);
    expect(registry.reserve(key, second), isFalse);
    expect(registry.take(key), same(first));
    expect(registry.take(key), isNull);
  });

  test('quarantine blocks reuse until the late response is observed', () {
    final registry = BleRequestRegistry<int>();
    final first = BleRequestSlot<int>(
      completer: Completer<int>(),
      generation: 7,
    );
    final replacement = BleRequestSlot<int>(
      completer: Completer<int>(),
      generation: 7,
    );

    expect(registry.reserve(key, first), isTrue);
    expect(registry.quarantineIfOwned(key, first), isTrue);
    expect(registry.isQuarantined(key), isTrue);
    expect(registry.reserve(key, replacement), isFalse);
    expect(registry.observeLateResponse(key), isTrue);
    expect(registry.reserve(key, replacement), isTrue);
  });

  test('an old completion cannot release a newer owner', () {
    final registry = BleRequestRegistry<int>();
    final old = BleRequestSlot<int>(completer: Completer<int>(), generation: 7);
    final current = BleRequestSlot<int>(
      completer: Completer<int>(),
      generation: 7,
    );

    expect(registry.reserve(key, old), isTrue);
    expect(registry.take(key), same(old));
    expect(registry.reserve(key, current), isTrue);
    expect(registry.releaseIfOwned(key, old), isFalse);
    expect(registry.take(key), same(current));
  });

  test('connection generations are independent request identities', () {
    final registry = BleRequestRegistry<int>();
    const newer = BleRequestKey(generation: 8, side: 'L', command: 0x25);
    final oldSlot = BleRequestSlot<int>(
      completer: Completer<int>(),
      generation: 7,
    );
    final newSlot = BleRequestSlot<int>(
      completer: Completer<int>(),
      generation: 8,
    );

    expect(registry.reserve(key, oldSlot), isTrue);
    expect(registry.reserve(newer, newSlot), isTrue);
  });
}
