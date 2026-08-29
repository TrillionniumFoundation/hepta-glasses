import 'dart:async';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';
import 'package:demo_ai_even/runtime/device_hal.dart';

final class SimulatedWrite {
  SimulatedWrite({
    required this.side,
    required this.bytes,
    required this.idempotencyKey,
    required this.sequence,
  });

  final GlassesSide side;
  final Uint8List bytes;
  final String idempotencyKey;
  final int sequence;
}

final class G1DigitalTwin implements GlassesTransport {
  G1DigitalTwin()
      : _connected = <GlassesSide, bool>{
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
        };

  final StreamController<DeviceConnectionSnapshot> _connectionController =
      StreamController<DeviceConnectionSnapshot>.broadcast();
  final Map<GlassesSide, bool> _connected;
  final Map<GlassesSide, int> _timeouts;
  final Map<GlassesSide, int> _nacks;
  final Map<GlassesSide, int> _indeterminateAfterWrites;
  final Map<String, String> _appliedFingerprints = <String, String>{};
  final List<SimulatedWrite> writes = <SimulatedWrite>[];
  int _sequence = 0;

  int get sendAttempts => _sequence;

  @override
  Stream<DeviceConnectionSnapshot> get connectionSnapshots =>
      _connectionController.stream;

  void setConnected(GlassesSide side, bool connected) {
    _connected[side] = connected;
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

    final fingerprint = sha256.convert(bytes).toString();
    final prior = _appliedFingerprints[idempotencyKey];
    if (prior != null && prior != fingerprint) {
      throw StateError(
        'Digital-twin idempotency key was reused with different bytes.',
      );
    }
    if (prior == null) {
      _appliedFingerprints[idempotencyKey] = fingerprint;
      writes.add(
        SimulatedWrite(
          side: side,
          bytes: Uint8List.fromList(bytes),
          idempotencyKey: idempotencyKey,
          sequence: _sequence,
        ),
      );
    }

    final indeterminateCount = _indeterminateAfterWrites[side] ?? 0;
    if (indeterminateCount > 0) {
      _indeterminateAfterWrites[side] = indeterminateCount - 1;
      return TransportAck(
        accepted: false,
        timeout: true,
        sequence: _sequence,
        errorCode: 'simulated_ack_lost_after_write',
        effectMayHaveOccurred: true,
      );
    }

    return TransportAck(
      accepted: true,
      timeout: false,
      sequence: _sequence,
      effectMayHaveOccurred: true,
    );
  }

  void _publishConnection() {
    DeviceLinkState stateFor(GlassesSide side) => (_connected[side] ?? false)
        ? DeviceLinkState.connected
        : DeviceLinkState.disconnected;

    _connectionController.add(
      DeviceConnectionSnapshot(
        left: stateFor(GlassesSide.left),
        right: stateFor(GlassesSide.right),
        observedAt: DateTime.now().toUtc(),
      ),
    );
  }

  Future<void> dispose() => _connectionController.close();
}
