import 'dart:async';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';
import 'package:demo_ai_even/ble_manager.dart';
import 'package:demo_ai_even/runtime/device_hal.dart';
import 'package:demo_ai_even/services/ble.dart';

/// Production-side adapter for the native BLE channel. Protocol and Agent code
/// depend on [GlassesTransport], not on the global platform-channel facade.
final class EvenG1Transport implements GlassesTransport {
  EvenG1Transport({BleManager? manager})
      : _manager = manager ?? BleManager.get() {
    _connectionSubscription = _manager.connectionSnapshots.listen(
      _publishConnectionSnapshot,
    );
    _publishConnectionSnapshot(_manager.connectionSnapshot);
  }

  final BleManager _manager;
  StreamSubscription<BleConnectionSnapshot>? _connectionSubscription;
  final StreamController<DeviceConnectionSnapshot> _connectionController =
      StreamController<DeviceConnectionSnapshot>.broadcast();
  final Map<String, String> _appliedFingerprints = <String, String>{};
  final Map<String, TransportAck> _receipts = <String, TransportAck>{};
  final Map<String, String> _attemptFingerprints = <String, String>{};
  final Map<String, Future<TransportAck>> _inFlight =
      <String, Future<TransportAck>>{};
  int _sequence = 0;

  @override
  Stream<DeviceConnectionSnapshot> get connectionSnapshots =>
      _connectionController.stream;

  void publishConnectionSnapshot() {
    _publishConnectionSnapshot(_manager.connectionSnapshot);
  }

  void _publishConnectionSnapshot(BleConnectionSnapshot snapshot) {
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
    final fingerprint = sha256.convert(bytes).toString();
    final priorFingerprint = _appliedFingerprints[idempotencyKey];
    if (priorFingerprint != null) {
      if (priorFingerprint != fingerprint) {
        throw StateError(
          'Device idempotency key was reused with different bytes.',
        );
      }
      return Future<TransportAck>.value(_receipts[idempotencyKey]!);
    }
    final inFlight = _inFlight[idempotencyKey];
    if (inFlight != null) {
      if (_attemptFingerprints[idempotencyKey] != fingerprint) {
        throw StateError(
          'Device idempotency key was reused concurrently with different bytes.',
        );
      }
      return inFlight;
    }

    final operation = _sendOnce(
      side: side,
      bytes: bytes,
      timeout: timeout,
      idempotencyKey: idempotencyKey,
      fingerprint: fingerprint,
    );
    late final Future<TransportAck> tracked;
    tracked = operation.whenComplete(() {
      if (identical(_inFlight[idempotencyKey], tracked)) {
        _inFlight.remove(idempotencyKey);
        _attemptFingerprints.remove(idempotencyKey);
      }
    });
    _attemptFingerprints[idempotencyKey] = fingerprint;
    _inFlight[idempotencyKey] = tracked;
    return tracked;
  }

  Future<TransportAck> _sendOnce({
    required GlassesSide side,
    required Uint8List bytes,
    required Duration timeout,
    required String idempotencyKey,
    required String fingerprint,
  }) async {
    _sequence++;
    final sequence = _sequence;
    final response = await BleManager.request(
      bytes,
      lr: side == GlassesSide.left ? 'L' : 'R',
      timeoutMs: timeout.inMilliseconds,
    );
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
      _appliedFingerprints[idempotencyKey] = fingerprint;
      _receipts[idempotencyKey] = receipt;
    }
    return receipt;
  }

  Future<void> dispose() async {
    await _connectionSubscription?.cancel();
    await _connectionController.close();
  }
}
