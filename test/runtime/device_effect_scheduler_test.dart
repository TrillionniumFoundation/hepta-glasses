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
    expect(await Future.wait<String>(<Future<String>>[first, second]), <String>[
      'first',
      'second',
    ]);
    expect(order, <String>[
      'first-start',
      'first-end',
      'second-start',
      'second-end',
    ]);
  });

  test('close fails closed when an effect never reaches idle', () async {
    final scheduler = DeviceEffectScheduler();
    final release = Completer<void>();
    final effect = scheduler.schedule<void>('blocked', () => release.future);
    await Future<void>.delayed(Duration.zero);

    await expectLater(
      scheduler.close(timeout: const Duration(milliseconds: 10)),
      throwsStateError,
    );
    await expectLater(
      scheduler.schedule<void>('late', () async {}),
      throwsA(isA<DeviceEffectSchedulerClosedException>()),
    );
    release.complete();
    await effect;
  });

  test('scheduler rejects work beyond its bounded capacity', () async {
    final scheduler = DeviceEffectScheduler(maxPending: 1);
    final release = Completer<void>();
    final first = scheduler.schedule<void>('first', () => release.future);
    await Future<void>.delayed(Duration.zero);

    await expectLater(
      scheduler.schedule<void>('second', () async {}),
      throwsA(isA<DeviceEffectQueueFullException>()),
    );
    release.complete();
    await first;
  });

  test('uncooperative effect times out and permanently opens the circuit',
      () async {
    final scheduler = DeviceEffectScheduler(
      defaultExecutionTimeout: const Duration(milliseconds: 10),
    );
    final never = Completer<void>();
    var laterEffectRan = false;

    await expectLater(
      scheduler.schedule<void>('uncertain-write', () => never.future),
      throwsA(isA<DeviceEffectTimeoutException>()),
    );

    expect(scheduler.circuitOpen, isTrue);
    expect(scheduler.indeterminateOperation, 'uncertain-write');
    expect(scheduler.pending, 0);
    await expectLater(
      scheduler.schedule<void>('later-write', () async {
        laterEffectRan = true;
      }),
      throwsA(isA<DeviceEffectCircuitOpenException>()),
    );
    expect(laterEffectRan, isFalse);
    await scheduler.close(timeout: const Duration(milliseconds: 50));
  });

  test('queued work is rejected rather than overlapping a timed-out effect',
      () async {
    final scheduler = DeviceEffectScheduler(
      maxPending: 2,
      defaultExecutionTimeout: const Duration(milliseconds: 10),
    );
    final never = Completer<void>();
    var secondRan = false;
    final first = scheduler.schedule<void>('first', () => never.future);
    final second = scheduler.schedule<void>('second', () async {
      secondRan = true;
    });

    await expectLater(first, throwsA(isA<DeviceEffectTimeoutException>()));
    await expectLater(
      second,
      throwsA(isA<DeviceEffectCircuitOpenException>()),
    );
    expect(secondRan, isFalse);
  });
}
