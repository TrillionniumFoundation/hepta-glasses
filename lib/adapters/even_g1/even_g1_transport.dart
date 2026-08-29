import 'dart:async';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';
import 'package:demo_ai_even/ble_manager.dart';
import 'package:demo_ai_even/runtime/device_hal.dart';

/// Production-side adapter for the existing native BLE channel. It is kept
/// behind [GlassesTransport] so protocol and Agent code do not depend on the
/// global platform-channel implementation.
final class EvenG1Transport implements GlassesTransport {
  EvenG1Transport({BleManager? manager}) : _manager = manager ?? BleManager.get();

  final BleManager _manager;
  final StreamController<DeviceConnectionSnapshot> _connectionController =
      StreamController<DeviceConnectionSnapshot>.broadcast();
  final Map<String, String> _appliedFingerprints = <String, String>{};
  final Map<String, TransportAck> _receipts = <String, TransportAck>{};
  int _sequence = 0;

  @override
  Stream<DeviceConnectionSnapshot> get connectionSnapshots =>
      _connectionController.stream;

  void publishConnectionSnapshot() {
    final state = _manager.isConnected
        ? DeviceLinkState.connected
        : DeviceLinkState.disconnected;
    _connectionController.add(
      DeviceConnectionSnapshot(
        left: state,
        right: state,
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
  }) async {
    final fingerprint = sha256.convert(bytes).toString();
    final priorFingerprint = _appliedFingerprints[idempotencyKey];
    if (priorFingerprint != null) {
      if (priorFingerprint != fingerprint) {
        throw StateError(
          'Device idempotency key was reused with different bytes.',
        );
      }
      return _receipts[idempotencyKey]!;
    }

    _sequence++;
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
      sequence: _sequence,
      errorCode: accepted
          ? null
          : response.isTimeout
              ? 'timeout'
              : 'negative_acknowledgement',
    );
    if (accepted) {
      _appliedFingerprints[idempotencyKey] = fingerprint;
      _receipts[idempotencyKey] = receipt;
    }
    return receipt;
  }

  Future<void> dispose() => _connectionController.close();
}
