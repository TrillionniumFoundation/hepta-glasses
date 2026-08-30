import 'dart:async';
import 'dart:collection';

final class _ScheduledEffect {
  const _ScheduledEffect(this.run);

  final Future<void> Function() run;
}

/// Serializes physical device effects. BLE control commands, multi-packet
/// display writes, settings mutations, and bulk transfers cannot interleave
/// through the deterministic runtime authority.
final class DeviceEffectScheduler {
  final Queue<_ScheduledEffect> _queue = Queue<_ScheduledEffect>();
  bool _draining = false;

  int get pending => _queue.length + (_draining ? 1 : 0);

  Future<T> schedule<T>(
    String operation,
    Future<T> Function() effect,
  ) {
    if (operation.trim().isEmpty) {
      throw ArgumentError.value(operation, 'operation', 'must not be empty');
    }
    final completer = Completer<T>();
    _queue.add(
      _ScheduledEffect(() async {
        try {
          completer.complete(await effect());
        } on Object catch (error, stackTrace) {
          completer.completeError(error, stackTrace);
        }
      }),
    );
    unawaited(_drain());
    return completer.future;
  }

  Future<void> _drain() async {
    if (_draining) {
      return;
    }
    _draining = true;
    try {
      while (_queue.isNotEmpty) {
        final item = _queue.removeFirst();
        await item.run();
      }
    } finally {
      _draining = false;
      if (_queue.isNotEmpty) {
        unawaited(_drain());
      }
    }
  }
}
