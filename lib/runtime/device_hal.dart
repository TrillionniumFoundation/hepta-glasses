import 'dart:typed_data';

enum GlassesSide { left, right }

enum DeviceLinkState {
  disconnected,
  connecting,
  discovering,
  connected,
  degraded,
}

final class DeviceConnectionSnapshot {
  const DeviceConnectionSnapshot({
    required this.left,
    required this.right,
    required this.observedAt,
  });

  final DeviceLinkState left;
  final DeviceLinkState right;
  final DateTime observedAt;

  bool get bothConnected =>
      left == DeviceLinkState.connected && right == DeviceLinkState.connected;

  bool get degraded =>
      left == DeviceLinkState.degraded ||
      right == DeviceLinkState.degraded ||
      (left == DeviceLinkState.connected) !=
          (right == DeviceLinkState.connected);
}

/// A transport acknowledgement separates delivery certainty from protocol
/// acceptance. A timeout after a native write is not proof that the device did
/// nothing; callers must reconcile before another physical write.
final class TransportAck {
  const TransportAck({
    required this.accepted,
    required this.timeout,
    required this.sequence,
    this.errorCode,
    this.effectMayHaveOccurred = false,
  });

  final bool accepted;
  final bool timeout;
  final int sequence;
  final String? errorCode;
  final bool effectMayHaveOccurred;

  bool get retrySafe => !accepted && !effectMayHaveOccurred;

  bool get requiresReconciliation => !accepted && effectMayHaveOccurred;

  Map<String, Object?> toJson() => <String, Object?>{
    'accepted': accepted,
    'timeout': timeout,
    'sequence': sequence,
    'error_code': errorCode,
    'effect_may_have_occurred': effectMayHaveOccurred,
  };
}

abstract interface class GlassesTransport {
  Stream<DeviceConnectionSnapshot> get connectionSnapshots;

  Future<TransportAck> send({
    required GlassesSide side,
    required Uint8List bytes,
    required Duration timeout,
    required String idempotencyKey,
  });
}
