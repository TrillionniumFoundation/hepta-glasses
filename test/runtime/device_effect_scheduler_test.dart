import 'dart:async';

import 'package:demo_ai_even/runtime/device_effect_scheduler.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('physical effects execute serially in submission order', () async {
    final scheduler = DeviceEffectScheduler();
    final firstGate = Completer<void>();
    final order = <String>[];

    final first = scheduler.schedule<String>('first', () async {
      order.add('first-start');
      await firstGate.future;
      order.add('first-end');
      return 'first';
    });
    final second = scheduler.schedule<String>('second', () async {
      order.add('second-start');
      order.add('second-end');
      return 'second';
    });

    await Future<void>.delayed(Duration.zero);
    expect(order, <String>['first-start']);
    firstGate.complete();
    expect(await Future.wait<String>(<Future<String>>[first, second]),
        <String>['first', 'second']);
    expect(
      order,
      <String>['first-start', 'first-end', 'second-start', 'second-end'],
    );
  });

  test('scheduler rejects work beyond its bounded capacity', () async {
    final scheduler = DeviceEffectScheduler(maxPending: 1);
    final release = Completer<void>();
    final first = scheduler.schedule<void>('first', () => release.future);
    await Future<void>.delayed(Duration.zero);

    await expectLater(
      scheduler.schedule<void>('second', () async {}),
      throwsStateError,
    );
    release.complete();
    await first;
  });
}
