import 'dart:async';

final class BleRequestKey {
  const BleRequestKey({
    required this.generation,
    required this.side,
    required this.command,
  })  : assert(generation >= 0),
        assert(side == 'L' || side == 'R'),
        assert(command >= 0 && command <= 0xff);

  final int generation;
  final String side;
  final int command;

  @override
  bool operator ==(Object other) =>
      other is BleRequestKey &&
      other.generation == generation &&
      other.side == side &&
      other.command == command;

  @override
  int get hashCode => Object.hash(generation, side, command);

  @override
  String toString() =>
      '$generation:$side:${command.toRadixString(16).padLeft(2, '0')}';
}

final class BleRequestSlot<T> {
  const BleRequestSlot({required this.completer, required this.generation});

  final Completer<T> completer;
  final int generation;
}

/// Owns exactly one waiter for each generation/side/command tuple.
///
/// A quarantined key cannot be reused until its late response is observed,
/// authoritative reconciliation releases it, or that exact generation is
/// replaced. Identity-aware release prevents an old completion path from
/// deleting a newer owner. A disconnect on one leg never releases quarantine
/// held by the other leg.
final class BleRequestRegistry<T> {
  final Map<BleRequestKey, BleRequestSlot<T>> _pending =
      <BleRequestKey, BleRequestSlot<T>>{};
  final Set<BleRequestKey> _quarantined = <BleRequestKey>{};

  bool contains(BleRequestKey key) => _pending.containsKey(key);

  bool get isEmpty => _pending.isEmpty;

  bool isQuarantined(BleRequestKey key) => _quarantined.contains(key);

  Set<BleRequestKey> get quarantinedKeys =>
      Set<BleRequestKey>.unmodifiable(_quarantined);

  bool reserve(BleRequestKey key, BleRequestSlot<T> slot) {
    if (_pending.containsKey(key) || _quarantined.contains(key)) {
      return false;
    }
    _pending[key] = slot;
    return true;
  }

  BleRequestSlot<T>? take(BleRequestKey key) => _pending.remove(key);

  bool releaseIfOwned(BleRequestKey key, BleRequestSlot<T> slot) {
    if (!identical(_pending[key], slot)) {
      return false;
    }
    _pending.remove(key);
    return true;
  }

  bool quarantineIfOwned(BleRequestKey key, BleRequestSlot<T> slot) {
    if (!releaseIfOwned(key, slot)) {
      return false;
    }
    _quarantined.add(key);
    return true;
  }

  bool observeLateResponse(BleRequestKey key) => _quarantined.remove(key);

  /// Removes pending owners selected by [predicate]. When [quarantine] is true,
  /// each removed key remains blocked because the write may already have
  /// reached the device.
  List<MapEntry<BleRequestKey, BleRequestSlot<T>>> takePendingWhere(
    bool Function(BleRequestKey key) predicate, {
    bool quarantine = false,
  }) {
    final selected = _pending.entries
        .where((MapEntry<BleRequestKey, BleRequestSlot<T>> entry) {
      return predicate(entry.key);
    }).toList(growable: false);
    for (final entry in selected) {
      _pending.remove(entry.key);
      if (quarantine) {
        _quarantined.add(entry.key);
      }
    }
    return selected;
  }

  List<MapEntry<BleRequestKey, BleRequestSlot<T>>> takeAllPending({
    bool quarantine = false,
  }) =>
      takePendingWhere((BleRequestKey _) => true, quarantine: quarantine);

  void clearQuarantineWhere(bool Function(BleRequestKey key) predicate) {
    _quarantined.removeWhere(predicate);
  }

  /// Generation replacement creates a new authority namespace, so only keys
  /// belonging to the retired generation may be released.
  void clearQuarantineForGeneration(int generation) {
    clearQuarantineWhere((BleRequestKey key) => key.generation == generation);
  }

  /// Used only after an authoritative reconciliation of the exact leg.
  void clearQuarantineForGenerationSide(int generation, String side) {
    assert(side == 'L' || side == 'R');
    clearQuarantineWhere(
      (BleRequestKey key) => key.generation == generation && key.side == side,
    );
  }

  /// Global clearing is intentionally reserved for terminal process disposal
  /// and deterministic test reset. Connection/disconnect paths must use a
  /// scoped method instead.
  void clearQuarantine() => _quarantined.clear();
}
