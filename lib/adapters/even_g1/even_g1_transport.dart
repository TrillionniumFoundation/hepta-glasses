import 'dart:async';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';
import 'package:demo_ai_even/ble_manager.dart';
import 'package:demo_ai_even/runtime/device_hal.dart';
import 'package:demo_ai_even/services/ble.dart';

typedef BleRequestSender = Future<BleReceive> Function(
  Uint8List bytes, {
  required String lr,
  required int timeoutMs,
  required int expectedGeneration,
  required String expectedPairIdentity,
});

typedef _AuthorityScope = ({
  int generation,
  String idempotencyKey,
  String pairIdentity,
  GlassesSide side,
});

typedef _AuthorityIdentity = ({
  int generation,
  String idempotencyKey,
  String pairIdentity,
  String payloadDigest,
  GlassesSide side,
});

/// Production-side adapter for the native BLE channel. Protocol and Agent code
/// depend on [GlassesTransport], not on the global platform-channel facade.
///
/// Every receipt and in-flight owner is scoped to a physical pair identity,
/// connection generation and leg. A caller string by itself is never device
/// authority and cannot suppress a write on another leg, reconnect or pair.
final class EvenG1Transport implements GlassesTransport {
  EvenG1Transport({
    BleConnectionSource? manager,
    BleRequestSender? requestSender,
    this.maxAuthorityEntries = 512,
  })  : _manager = manager ?? BleManager.get(),
        _requestSender = requestSender ?? _requestThroughManager {
    if (maxAuthorityEntries < 1) {
      throw ArgumentError.value(
        maxAuthorityEntries,
        'maxAuthorityEntries',
        'must be positive',
      );
    }
    _connectionSubscription = _manager.connectionSnapshots.listen(
      _publishConnectionSnapshot,
    );
    _publishConnectionSnapshot(_manager.connectionSnapshot);
  }

  final BleConnectionSource _manager;
  final BleRequestSender _requestSender;
  final int maxAuthorityEntries;
  StreamSubscription<BleConnectionSnapshot>? _connectionSubscription;
  final StreamController<DeviceConnectionSnapshot> _connectionController =
      StreamController<DeviceConnectionSnapshot>.broadcast();
  final Map<_AuthorityScope, String> _claimedDigests =
      <_AuthorityScope, String>{};
  final Map<_AuthorityIdentity, TransportAck> _receipts =
      <_AuthorityIdentity, TransportAck>{};
  final Map<_AuthorityIdentity, Future<TransportAck>> _inFlight =
      <_AuthorityIdentity, Future<TransportAck>>{};
  int _sequence = 0;

  static Future<BleReceive> _requestThroughManager(
    Uint8List bytes, {
    required String lr,
    required int timeoutMs,
    required int expectedGeneration,
    required String expectedPairIdentity,
  }) =>
      BleManager.request(
        bytes,
        lr: lr,
        timeoutMs: timeoutMs,
        expectedGeneration: expectedGeneration,
        expectedPairIdentity: expectedPairIdentity,
      );

  @override
  Stream<DeviceConnectionSnapshot> get connectionSnapshots =>
      _connectionController.stream;

  void publishConnectionSnapshot() {
    _publishConnectionSnapshot(_manager.connectionSnapshot);
  }

  void _publishConnectionSnapshot(BleConnectionSnapshot snapshot) {
    _retireCompletedPriorAuthorities(snapshot);
    if (_connectionController.isClosed) {
      return;
    }
    _connectionController.add(
      DeviceConnectionSnapshot(
        left: snapshot.leftConnected
            ? DeviceLinkState.connected
            : DeviceLinkState.disconnected,
        right: snapshot.rightConnected
            ? DeviceLinkState.connected
            : DeviceLinkState.disconnected,
        observedAt: DateTime.now().toUtc(),
        generation: snapshot.generation,
        pairIdentity: snapshot.pairIdentity,
      ),
    );
  }

  @override
  Future<TransportAck> send({
    required GlassesSide side,
    required Uint8List bytes,
    required Duration timeout,
    required String idempotencyKey,
  }) {
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

    final snapshot = _manager.connectionSnapshot;
    if (!snapshot.hasAuthoritativeIdentity) {
      return Future<TransportAck>.value(
        _preWriteRejection('connection_authority_unavailable'),
      );
    }
    final sideCode = side == GlassesSide.left ? 'L' : 'R';
    if (!snapshot.isSideConnected(sideCode)) {
      return Future<TransportAck>.value(
        _preWriteRejection('side_disconnected'),
      );
    }

    final payloadDigest = sha256.convert(bytes).toString();
    final scope = (
      generation: snapshot.generation,
      idempotencyKey: normalizedKey,
      pairIdentity: snapshot.pairIdentity,
      side: side,
    );
    final identity = (
      generation: snapshot.generation,
      idempotencyKey: normalizedKey,
      pairIdentity: snapshot.pairIdentity,
      payloadDigest: payloadDigest,
      side: side,
    );

    final claimedDigest = _claimedDigests[scope];
    if (claimedDigest != null && claimedDigest != payloadDigest) {
      throw StateError(
        'Device idempotency authority was reused with different bytes.',
      );
    }
    final receipt = _receipts[identity];
    if (receipt != null) {
      return Future<TransportAck>.value(receipt);
    }
    final active = _inFlight[identity];
    if (active != null) {
      return active;
    }
    if (claimedDigest == null &&
        _claimedDigests.length >= maxAuthorityEntries) {
      return Future<TransportAck>.value(
        _preWriteRejection('idempotency_authority_capacity_exhausted'),
      );
    }

    _claimedDigests[scope] = payloadDigest;
    final operation = _sendOnce(
      sideCode: sideCode,
      bytes: Uint8List.fromList(bytes),
      timeout: timeout,
      identity: identity,
    );
    late final Future<TransportAck> tracked;
    tracked = operation.whenComplete(() {
      if (identical(_inFlight[identity], tracked)) {
        _inFlight.remove(identity);
      }
      if (!_receipts.containsKey(identity)) {
        _claimedDigests.remove(scope);
      }
      _retireCompletedPriorAuthorities(_manager.connectionSnapshot);
    });
    _inFlight[identity] = tracked;
    return tracked;
  }

  Future<TransportAck> _sendOnce({
    required String sideCode,
    required Uint8List bytes,
    required Duration timeout,
    required _AuthorityIdentity identity,
  }) async {
    final beforeWrite = _manager.connectionSnapshot;
    if (!_matchesAuthority(beforeWrite, identity) ||
        !beforeWrite.isSideConnected(sideCode)) {
      return _preWriteRejection('connection_changed_before_native_write');
    }

    final sequence = ++_sequence;
    final response = await _requestSender(
      bytes,
      lr: sideCode,
      timeoutMs: timeout.inMilliseconds,
      expectedGeneration: identity.generation,
      expectedPairIdentity: identity.pairIdentity,
    );

    final responseAuthorityMatches = response.hasAuthoritativeIdentity &&
        response.generation == identity.generation &&
        response.pairIdentity == identity.pairIdentity;
    if (!responseAuthorityMatches) {
      final uncertain = TransportAck(
        accepted: false,
        timeout: true,
        sequence: sequence,
        errorCode: 'native_response_authority_mismatch',
        effectMayHaveOccurred: true,
      );
      _receipts[identity] = uncertain;
      return uncertain;
    }

    final accepted = !response.isTimeout &&
        response.data.length > 1 &&
        (response.data[1] == 0xc9 || response.data[1] == 0xcb);
    final receipt = TransportAck(
      accepted: accepted,
      timeout: response.isTimeout,
      sequence: sequence,
      errorCode: accepted
          ? null
          : response.errorCode ??
              (response.isTimeout
                  ? 'timeout_after_native_write'
                  : 'negative_acknowledgement'),
      effectMayHaveOccurred: accepted || response.effectMayHaveOccurred,
    );
    if (accepted || receipt.requiresReconciliation) {
      _receipts[identity] = receipt;
    }
    return receipt;
  }

  bool _matchesAuthority(
    BleConnectionSnapshot snapshot,
    _AuthorityIdentity identity,
  ) =>
      snapshot.generation == identity.generation &&
      snapshot.pairIdentity == identity.pairIdentity;

  TransportAck _preWriteRejection(String errorCode) => TransportAck(
        accepted: false,
        timeout: false,
        sequence: ++_sequence,
        errorCode: errorCode,
        effectMayHaveOccurred: false,
      );

  void _retireCompletedPriorAuthorities(BleConnectionSnapshot current) {
    bool isCurrentScope(_AuthorityScope scope) =>
        scope.generation == current.generation &&
        scope.pairIdentity == current.pairIdentity;

    bool hasInFlight(_AuthorityScope scope) => _inFlight.keys.any(
          (_AuthorityIdentity identity) =>
              identity.generation == scope.generation &&
              identity.pairIdentity == scope.pairIdentity &&
              identity.side == scope.side &&
              identity.idempotencyKey == scope.idempotencyKey,
        );

    final retiredScopes = _claimedDigests.keys
        .where(
          (_AuthorityScope scope) =>
              !isCurrentScope(scope) && !hasInFlight(scope),
        )
        .toList(growable: false);
    for (final scope in retiredScopes) {
      _claimedDigests.remove(scope);
      _receipts.removeWhere(
        (_AuthorityIdentity identity, TransportAck _) =>
            identity.generation == scope.generation &&
            identity.pairIdentity == scope.pairIdentity &&
            identity.side == scope.side &&
            identity.idempotencyKey == scope.idempotencyKey,
      );
    }
  }

  Future<void> dispose() async {
    await _connectionSubscription?.cancel();
    await _connectionController.close();
  }
}
