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
  const BleRequestSlot({
    required this.completer,
    required this.generation,
  });

  final Completer<T> completer;
  final int generation;
}

/// Owns exactly one waiter for each generation/side/command tuple.
///
/// A quarantined key cannot be reused until its late response is observed or
/// the connection generation is replaced. Identity-aware release prevents an
/// old completion path from deleting a newer owner.
final class BleRequestRegistry<T> {
  final Map<BleRequestKey, BleRequestSlot<T>> _pending =
      <BleRequestKey, BleRequestSlot<T>>{};
  final Set<BleRequestKey> _quarantined = <BleRequestKey>{};

  bool contains(BleRequestKey key) => _pending.containsKey(key);

  bool get isEmpty => _pending.isEmpty;

  bool isQuarantined(BleRequestKey key) => _quarantined.contains(key);

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

  List<MapEntry<BleRequestKey, BleRequestSlot<T>>> takeAllPending() {
    final entries = List<MapEntry<BleRequestKey, BleRequestSlot<T>>>.of(
      _pending.entries,
    );
    _pending.clear();
    return entries;
  }

  void clearQuarantine() => _quarantined.clear();
}
