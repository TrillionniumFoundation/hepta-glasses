import 'dart:async';
import 'dart:collection';

final class DeviceEffectQueueFullException implements Exception {
  const DeviceEffectQueueFullException(this.maximumPending);

  final int maximumPending;

  @override
  String toString() =>
      'DeviceEffectQueueFullException(maximumPending: $maximumPending)';
}

final class DeviceEffectSchedulerClosedException implements Exception {
  const DeviceEffectSchedulerClosedException();

  @override
  String toString() => 'DeviceEffectSchedulerClosedException()';
}

final class DeviceEffectTimeoutException implements Exception {
  const DeviceEffectTimeoutException({
    required this.operation,
    required this.timeout,
  });

  final String operation;
  final Duration timeout;

  @override
  String toString() =>
      'DeviceEffectTimeoutException(operation: $operation, timeout: $timeout)';
}

final class DeviceEffectCircuitOpenException implements Exception {
  const DeviceEffectCircuitOpenException(this.indeterminateOperation);

  final String indeterminateOperation;

  @override
  String toString() =>
      'DeviceEffectCircuitOpenException('
      'indeterminateOperation: $indeterminateOperation)';
}

final class _ScheduledEffect {
  const _ScheduledEffect({required this.run, required this.reject});

  final Future<void> Function() run;
  final void Function(Object error, StackTrace stackTrace) reject;
}

/// Serializes physical device effects. BLE control commands, multi-packet
/// display writes, settings mutations, and bulk transfers cannot interleave
/// through the deterministic runtime authority.
///
/// An uncooperative effect is detached after its bounded execution deadline and
/// permanently opens the process-local circuit. The queue is released, but no
/// later device mutation is admitted in the same process. This avoids both a
/// permanently occupied scheduler and unsafe overlap with a late physical
/// effect whose completion cannot be cancelled or proven.
final class DeviceEffectScheduler {
  DeviceEffectScheduler({
    this.maxPending = 64,
    this.defaultExecutionTimeout = const Duration(seconds: 30),
  }) {
    if (maxPending < 1) {
      throw ArgumentError.value(maxPending, 'maxPending', 'must be positive');
    }
    if (defaultExecutionTimeout <= Duration.zero) {
      throw ArgumentError.value(
        defaultExecutionTimeout,
        'defaultExecutionTimeout',
        'must be positive',
      );
    }
  }

  final int maxPending;
  final Duration defaultExecutionTimeout;
  final Queue<_ScheduledEffect> _queue = Queue<_ScheduledEffect>();
  bool _draining = false;
  bool _closed = false;
  String? _indeterminateOperation;
  Completer<void>? _idleCompleter;

  int get pending => _queue.length + (_draining ? 1 : 0);

  bool get circuitOpen => _indeterminateOperation != null;

  String? get indeterminateOperation => _indeterminateOperation;

  Future<T> schedule<T>(
    String operation,
    Future<T> Function() effect, {
    Duration? executionTimeout,
  }) {
    final normalizedOperation = operation.trim();
    if (normalizedOperation.isEmpty) {
      throw ArgumentError.value(operation, 'operation', 'must not be empty');
    }
    final timeout = executionTimeout ?? defaultExecutionTimeout;
    if (timeout <= Duration.zero) {
      throw ArgumentError.value(
        timeout,
        'executionTimeout',
        'must be positive',
      );
    }
    if (_closed) {
      return Future<T>.error(const DeviceEffectSchedulerClosedException());
    }
    final blockedBy = _indeterminateOperation;
    if (blockedBy != null) {
      return Future<T>.error(DeviceEffectCircuitOpenException(blockedBy));
    }
    if (pending >= maxPending) {
      return Future<T>.error(DeviceEffectQueueFullException(maxPending));
    }

    final completer = Completer<T>();
    _idleCompleter ??= Completer<void>();
    _queue.add(
      _ScheduledEffect(
        run: () async {
          Future<T> operationFuture;
          try {
            operationFuture = effect();
          } on Object catch (error, stackTrace) {
            if (!completer.isCompleted) {
              completer.completeError(error, stackTrace);
            }
            return;
          }

          try {
            final value = await operationFuture.timeout(timeout);
            if (!completer.isCompleted) {
              completer.complete(value);
            }
          } on TimeoutException catch (_, stackTrace) {
            // Consume any eventual completion/error. It cannot regain authority
            // or complete the caller after the timeout boundary.
            unawaited(
              operationFuture.then<void>(
                (_) {},
                onError: (Object _, StackTrace __) {},
              ),
            );
            _indeterminateOperation ??= normalizedOperation;
            if (!completer.isCompleted) {
              completer.completeError(
                DeviceEffectTimeoutException(
                  operation: normalizedOperation,
                  timeout: timeout,
                ),
                stackTrace,
              );
            }
          } on Object catch (error, stackTrace) {
            if (!completer.isCompleted) {
              completer.completeError(error, stackTrace);
            }
          }
        },
        reject: (Object error, StackTrace stackTrace) {
          if (!completer.isCompleted) {
            completer.completeError(error, stackTrace);
          }
        },
      ),
    );
    unawaited(_drain());
    return completer.future;
  }

  Future<void> close({Duration timeout = const Duration(seconds: 30)}) async {
    if (timeout <= Duration.zero) {
      throw ArgumentError.value(timeout, 'timeout', 'must be positive');
    }
    _closed = true;
    final idle = _idleCompleter?.future;
    if (idle == null) {
      return;
    }
    try {
      await idle.timeout(timeout);
    } on TimeoutException {
      throw StateError('Device effect scheduler did not become idle.');
    }
  }

  Future<void> _drain() async {
    if (_draining) {
      return;
    }
    _draining = true;
    try {
      while (_queue.isNotEmpty) {
        final blockedBy = _indeterminateOperation;
        if (blockedBy != null) {
          final error = DeviceEffectCircuitOpenException(blockedBy);
          final stackTrace = StackTrace.current;
          while (_queue.isNotEmpty) {
            _queue.removeFirst().reject(error, stackTrace);
          }
          break;
        }
        final item = _queue.removeFirst();
        await item.run();
      }
    } finally {
      _draining = false;
      if (_queue.isNotEmpty && _indeterminateOperation == null) {
        unawaited(_drain());
      } else {
        final idle = _idleCompleter;
        _idleCompleter = null;
        if (idle != null && !idle.isCompleted) {
          idle.complete();
        }
      }
    }
  }
}
