import 'dart:typed_data';

enum GlassesSide { left, right }

enum DeviceLinkState { disconnected, connecting, connected, degraded }

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

final class TransportAck {
  const TransportAck({
    required this.accepted,
    required this.timeout,
    required this.sequence,
    this.errorCode,
  });

  final bool accepted;
  final bool timeout;
  final int sequence;
  final String? errorCode;
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
