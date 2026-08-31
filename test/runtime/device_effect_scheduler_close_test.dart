import 'dart:async';

import 'package:demo_ai_even/runtime/device_effect_scheduler.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('close completes when the queued effect becomes idle', () async {
    final scheduler = DeviceEffectScheduler();
    final release = Completer<void>();
    final effect = scheduler.schedule<void>('wait', () => release.future);
    final closing = scheduler.close(timeout: const Duration(seconds: 1));
    release.complete();
    await effect;
    await closing;
  });
  test('close has a bounded timeout for a stuck physical effect', () async {
    final scheduler = DeviceEffectScheduler();
    final never = Completer<void>();
    unawaited(scheduler.schedule<void>('stuck', () => never.future));
    await expectLater(
        scheduler.close(timeout: const Duration(milliseconds: 10)),
        throwsA(isA<TimeoutException>()));
    never.complete();
  });
}
