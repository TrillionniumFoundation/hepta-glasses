import 'dart:async';
import 'dart:collection';

final class _ScheduledEffect {
  const _ScheduledEffect(this.run);
  final Future<void> Function() run;
}

final class DeviceEffectScheduler {
  DeviceEffectScheduler({this.maxPending = 64}) {
    if (maxPending < 1) {
      throw ArgumentError.value(maxPending, 'maxPending', 'must be positive');
    }
  }

  final int maxPending;
  final Queue<_ScheduledEffect> _queue = Queue<_ScheduledEffect>();
  bool _draining = false;
  bool _closed = false;
  Completer<void>? _idle;

  int get pending => _queue.length + (_draining ? 1 : 0);

  Future<T> schedule<T>(String operation, Future<T> Function() effect) {
    if (operation.trim().isEmpty) {
      throw ArgumentError.value(operation, 'operation', 'must not be empty');
    }
    if (_closed) {
      return Future<T>.error(StateError('Device effect scheduler is closed.'));
    }
    if (pending >= maxPending) {
      return Future<T>.error(
          StateError('Device effect scheduler capacity exceeded.'));
    }
    _idle ??= Completer<void>();
    final completer = Completer<T>();
    _queue.add(_ScheduledEffect(() async {
      try {
        completer.complete(await effect());
      } on Object catch (error, stackTrace) {
        completer.completeError(error, stackTrace);
      }
    }));
    unawaited(_drain());
    return completer.future;
  }

  Future<void> close({Duration timeout = const Duration(seconds: 30)}) async {
    if (timeout <= Duration.zero) {
      throw ArgumentError.value(timeout, 'timeout', 'must be positive');
    }
    _closed = true;
    final idle = _idle;
    if (idle != null && !idle.isCompleted) {
      await idle.future.timeout(timeout,
          onTimeout: () => throw TimeoutException(
              'Device effect scheduler did not become idle.', timeout));
    }
  }

  Future<void> _drain() async {
    if (_draining) return;
    _draining = true;
    try {
      while (_queue.isNotEmpty) {
        await _queue.removeFirst().run();
      }
    } finally {
      _draining = false;
      if (_queue.isNotEmpty) {
        unawaited(_drain());
      } else {
        final idle = _idle;
        _idle = null;
        if (idle != null && !idle.isCompleted) idle.complete();
      }
    }
  }
}
