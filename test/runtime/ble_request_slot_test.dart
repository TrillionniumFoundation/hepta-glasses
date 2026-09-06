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

  test('one-leg disconnect selection cannot release opposite-leg quarantine',
      () {
    final registry = BleRequestRegistry<int>();
    const left = BleRequestKey(generation: 9, side: 'L', command: 0x4e);
    const right = BleRequestKey(generation: 9, side: 'R', command: 0x4e);
    final leftSlot = BleRequestSlot<int>(
      completer: Completer<int>(),
      generation: 9,
    );
    final rightSlot = BleRequestSlot<int>(
      completer: Completer<int>(),
      generation: 9,
    );

    expect(registry.reserve(left, leftSlot), isTrue);
    expect(registry.reserve(right, rightSlot), isTrue);
    expect(registry.quarantineIfOwned(left, leftSlot), isTrue);
    expect(registry.quarantineIfOwned(right, rightSlot), isTrue);

    registry.clearQuarantineForGenerationSide(9, 'L');

    expect(registry.isQuarantined(left), isFalse);
    expect(registry.isQuarantined(right), isTrue);
  });

  test('generation replacement clears only the retired namespace', () {
    final registry = BleRequestRegistry<int>();
    const retired = BleRequestKey(generation: 12, side: 'R', command: 0x25);
    const current = BleRequestKey(generation: 13, side: 'R', command: 0x25);
    final retiredSlot = BleRequestSlot<int>(
      completer: Completer<int>(),
      generation: 12,
    );
    final currentSlot = BleRequestSlot<int>(
      completer: Completer<int>(),
      generation: 13,
    );

    expect(registry.reserve(retired, retiredSlot), isTrue);
    expect(registry.reserve(current, currentSlot), isTrue);
    expect(registry.quarantineIfOwned(retired, retiredSlot), isTrue);
    expect(registry.quarantineIfOwned(current, currentSlot), isTrue);

    registry.clearQuarantineForGeneration(12);

    expect(registry.isQuarantined(retired), isFalse);
    expect(registry.isQuarantined(current), isTrue);
  });

  test('disconnect can quarantine only selected pending owners', () {
    final registry = BleRequestRegistry<int>();
    const left = BleRequestKey(generation: 21, side: 'L', command: 0x0e);
    const right = BleRequestKey(generation: 21, side: 'R', command: 0x0e);
    final leftSlot = BleRequestSlot<int>(
      completer: Completer<int>(),
      generation: 21,
    );
    final rightSlot = BleRequestSlot<int>(
      completer: Completer<int>(),
      generation: 21,
    );
    registry.reserve(left, leftSlot);
    registry.reserve(right, rightSlot);

    final removed = registry.takePendingWhere(
      (BleRequestKey candidate) => candidate.side == 'L',
      quarantine: true,
    );

    expect(removed.single.key, left);
    expect(registry.isQuarantined(left), isTrue);
    expect(registry.contains(right), isTrue);
    expect(registry.isQuarantined(right), isFalse);
  });
}
