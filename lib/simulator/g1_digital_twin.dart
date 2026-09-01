import 'dart:async';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';
import 'package:demo_ai_even/runtime/device_hal.dart';

typedef _TwinAuthorityScope = ({
  int generation,
  String idempotencyKey,
  String pairIdentity,
  GlassesSide side,
});

typedef _TwinAuthorityIdentity = ({
  int generation,
  String idempotencyKey,
  String pairIdentity,
  String payloadDigest,
  GlassesSide side,
});

final class SimulatedWrite {
  SimulatedWrite({
    required this.side,
    required this.bytes,
    required this.idempotencyKey,
    required this.sequence,
    required this.generation,
    required this.pairIdentity,
  });

  final GlassesSide side;
  final Uint8List bytes;
  final String idempotencyKey;
  final int sequence;
  final int generation;
  final String pairIdentity;
}

/// Deterministic source-level model of the G1 transport authority boundary.
///
/// The twin intentionally shares the production transport's composite
/// idempotency domain. A caller key from another leg, connection generation, or
/// selected pair can never suppress a required simulated physical write.
final class G1DigitalTwin implements GlassesTransport {
  G1DigitalTwin({
    String pairIdentity = 'digital-twin-pair-1',
    int generation = 1,
    this.maxAuthorityEntries = 512,
  })  : _pairIdentity = pairIdentity.trim(),
        _generation = generation,
        _connected = <GlassesSide, bool>{
          GlassesSide.left: true,
          GlassesSide.right: true,
        },
        _timeouts = <GlassesSide, int>{
          GlassesSide.left: 0,
          GlassesSide.right: 0,
        },
        _nacks = <GlassesSide, int>{
          GlassesSide.left: 0,
          GlassesSide.right: 0,
        },
        _indeterminateAfterWrites = <GlassesSide, int>{
          GlassesSide.left: 0,
          GlassesSide.right: 0,
        } {
    if (_generation < 1) {
      throw ArgumentError.value(generation, 'generation', 'must be positive');
    }
    if (_pairIdentity.isEmpty || _pairIdentity == 'unselected') {
      throw ArgumentError.value(
        pairIdentity,
        'pairIdentity',
        'must identify an authoritative simulated pair',
      );
    }
    if (maxAuthorityEntries < 1) {
      throw ArgumentError.value(
        maxAuthorityEntries,
        'maxAuthorityEntries',
        'must be positive',
      );
    }
  }

  final int maxAuthorityEntries;
  final StreamController<DeviceConnectionSnapshot> _connectionController =
      StreamController<DeviceConnectionSnapshot>.broadcast();
  final Map<GlassesSide, bool> _connected;
  final Map<GlassesSide, int> _timeouts;
  final Map<GlassesSide, int> _nacks;
  final Map<GlassesSide, int> _indeterminateAfterWrites;
  final Map<_TwinAuthorityScope, String> _claimedDigests =
      <_TwinAuthorityScope, String>{};
  final Map<_TwinAuthorityIdentity, TransportAck> _receipts =
      <_TwinAuthorityIdentity, TransportAck>{};
  final List<SimulatedWrite> writes = <SimulatedWrite>[];
  int _sequence = 0;
  int _generation;
  String _pairIdentity;

  int get sendAttempts => _sequence;
  int get generation => _generation;
  String get pairIdentity => _pairIdentity;

  DeviceConnectionSnapshot get connectionSnapshot => DeviceConnectionSnapshot(
        left: _stateFor(GlassesSide.left),
        right: _stateFor(GlassesSide.right),
        observedAt: DateTime.now().toUtc(),
        generation: _generation,
        pairIdentity: _pairIdentity,
      );

  @override
  Stream<DeviceConnectionSnapshot> get connectionSnapshots =>
      _connectionController.stream;

  void setConnected(GlassesSide side, bool connected) {
    _connected[side] = connected;
    _publishConnection();
  }

  /// Starts a new connection authority namespace, optionally selecting a new
  /// pair. Completed receipts from the retired namespace are discarded exactly
  /// as the production adapter retires old pair/generation authority.
  void advanceGeneration({String? pairIdentity}) {
    final nextPair = pairIdentity?.trim();
    if (nextPair != null &&
        (nextPair.isEmpty || nextPair == 'unselected')) {
      throw ArgumentError.value(
        pairIdentity,
        'pairIdentity',
        'must identify an authoritative simulated pair',
      );
    }
    _generation++;
    if (nextPair != null) {
      _pairIdentity = nextPair;
    }
    _claimedDigests.clear();
    _receipts.clear();
    _publishConnection();
  }

  /// Injects a timeout before the simulated write reaches the device. This is
  /// retry-safe and differs from [injectIndeterminateAfterWrites].
  void injectTimeouts(GlassesSide side, int count) {
    if (count < 0) {
      throw ArgumentError.value(count, 'count');
    }
    _timeouts[side] = count;
  }

  void injectNacks(GlassesSide side, int count) {
    if (count < 0) {
      throw ArgumentError.value(count, 'count');
    }
    _nacks[side] = count;
  }

  /// Applies the write but drops its acknowledgement. A caller must reconcile
  /// instead of retrying because the physical effect may already exist.
  void injectIndeterminateAfterWrites(GlassesSide side, int count) {
    if (count < 0) {
      throw ArgumentError.value(count, 'count');
    }
    _indeterminateAfterWrites[side] = count;
  }

  @override
  Future<TransportAck> send({
    required GlassesSide side,
    required Uint8List bytes,
    required Duration timeout,
    required String idempotencyKey,
  }) async {
    final normalizedKey = idempotencyKey.trim();
    if (normalizedKey.isEmpty) {
      throw ArgumentError.value(idempotencyKey, 'idempotencyKey');
    }
    if (bytes.isEmpty) {
      throw ArgumentError.value(bytes, 'bytes', 'must not be empty');
    }
    if (timeout <= Duration.zero) {
      throw ArgumentError.value(timeout, 'timeout', 'must be positive');
    }

    final payloadDigest = sha256.convert(bytes).toString();
    final scope = (
      generation: _generation,
      idempotencyKey: normalizedKey,
      pairIdentity: _pairIdentity,
      side: side,
    );
    final identity = (
      generation: _generation,
      idempotencyKey: normalizedKey,
      pairIdentity: _pairIdentity,
      payloadDigest: payloadDigest,
      side: side,
    );

    final claimedDigest = _claimedDigests[scope];
    if (claimedDigest != null && claimedDigest != payloadDigest) {
      throw StateError(
        'Digital-twin idempotency authority was reused with different bytes.',
      );
    }
    final existing = _receipts[identity];
    if (existing != null) {
      return existing;
    }

    _sequence++;
    if (!(_connected[side] ?? false)) {
      return TransportAck(
        accepted: false,
        timeout: false,
        sequence: _sequence,
        errorCode: 'side_disconnected',
      );
    }
    final timeoutCount = _timeouts[side] ?? 0;
    if (timeoutCount > 0) {
      _timeouts[side] = timeoutCount - 1;
      return TransportAck(
        accepted: false,
        timeout: true,
        sequence: _sequence,
        errorCode: 'simulated_pre_write_timeout',
      );
    }
    final nackCount = _nacks[side] ?? 0;
    if (nackCount > 0) {
      _nacks[side] = nackCount - 1;
      return TransportAck(
        accepted: false,
        timeout: false,
        sequence: _sequence,
        errorCode: 'simulated_nack',
      );
    }
    if (claimedDigest == null &&
        _claimedDigests.length >= maxAuthorityEntries) {
      return TransportAck(
        accepted: false,
        timeout: false,
        sequence: _sequence,
        errorCode: 'idempotency_authority_capacity_exhausted',
      );
    }

    _claimedDigests[scope] = payloadDigest;
    writes.add(
      SimulatedWrite(
        side: side,
        bytes: Uint8List.fromList(bytes),
        idempotencyKey: normalizedKey,
        sequence: _sequence,
        generation: _generation,
        pairIdentity: _pairIdentity,
      ),
    );

    final indeterminateCount = _indeterminateAfterWrites[side] ?? 0;
    if (indeterminateCount > 0) {
      _indeterminateAfterWrites[side] = indeterminateCount - 1;
      final receipt = TransportAck(
        accepted: false,
        timeout: true,
        sequence: _sequence,
        errorCode: 'simulated_ack_lost_after_write',
        effectMayHaveOccurred: true,
      );
      _receipts[identity] = receipt;
      return receipt;
    }

    final receipt = TransportAck(
      accepted: true,
      timeout: false,
      sequence: _sequence,
      effectMayHaveOccurred: true,
    );
    _receipts[identity] = receipt;
    return receipt;
  }

  DeviceLinkState _stateFor(GlassesSide side) => (_connected[side] ?? false)
      ? DeviceLinkState.connected
      : DeviceLinkState.disconnected;

  void _publishConnection() {
    if (!_connectionController.isClosed) {
      _connectionController.add(connectionSnapshot);
    }
  }

  Future<void> dispose() => _connectionController.close();
}
