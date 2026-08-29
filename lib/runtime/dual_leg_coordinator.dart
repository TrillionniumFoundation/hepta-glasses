import 'dart:typed_data';

import 'package:crypto/crypto.dart';

import 'device_hal.dart';

final class DualLegReceipt {
  const DualLegReceipt({
    required this.idempotencyKey,
    required this.left,
    required this.right,
    this.replayed = false,
  });

  final String idempotencyKey;
  final TransportAck left;
  final TransportAck right;
  final bool replayed;

  bool get complete => left.accepted && right.accepted;

  bool get degraded => !complete;

  DualLegReceipt asReplay() => DualLegReceipt(
        idempotencyKey: idempotencyKey,
        left: left,
        right: right,
        replayed: true,
      );
}

final class DualLegCoordinator {
  DualLegCoordinator({
    required GlassesTransport transport,
    this.maxAttempts = 3,
    this.timeout = const Duration(seconds: 2),
  }) : _transport = transport {
    if (maxAttempts < 1) {
      throw ArgumentError.value(maxAttempts, 'maxAttempts', 'must be positive');
    }
  }

  final GlassesTransport _transport;
  final int maxAttempts;
  final Duration timeout;
  final Map<String, DualLegReceipt> _receipts = <String, DualLegReceipt>{};
  final Map<String, String> _fingerprints = <String, String>{};

  Future<DualLegReceipt> sendMirrored({
    required Uint8List bytes,
    required String idempotencyKey,
  }) async {
    if (idempotencyKey.trim().isEmpty) {
      throw ArgumentError.value(idempotencyKey, 'idempotencyKey');
    }
    final fingerprint = sha256.convert(bytes).toString();
    final existing = _receipts[idempotencyKey];
    if (existing != null) {
      if (_fingerprints[idempotencyKey] != fingerprint) {
        throw StateError(
          'Idempotency key was reused with different device bytes.',
        );
      }
      return existing.asReplay();
    }

    final left = await _sendWithRetry(
      side: GlassesSide.left,
      bytes: bytes,
      idempotencyKey: '$idempotencyKey:left',
    );
    final right = await _sendWithRetry(
      side: GlassesSide.right,
      bytes: bytes,
      idempotencyKey: '$idempotencyKey:right',
    );
    final receipt = DualLegReceipt(
      idempotencyKey: idempotencyKey,
      left: left,
      right: right,
    );
    _fingerprints[idempotencyKey] = fingerprint;
    _receipts[idempotencyKey] = receipt;
    return receipt;
  }

  Future<TransportAck> _sendWithRetry({
    required GlassesSide side,
    required Uint8List bytes,
    required String idempotencyKey,
  }) async {
    TransportAck last = const TransportAck(
      accepted: false,
      timeout: false,
      sequence: -1,
      errorCode: 'not_attempted',
    );
    for (var attempt = 1; attempt <= maxAttempts; attempt++) {
      last = await _transport.send(
        side: side,
        bytes: bytes,
        timeout: timeout,
        idempotencyKey: idempotencyKey,
      );
      if (last.accepted) {
        return last;
      }
    }
    return last;
  }
}
