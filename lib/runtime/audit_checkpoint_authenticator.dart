import 'dart:convert';

import 'package:crypto/crypto.dart';
import 'package:flutter/services.dart';

abstract interface class AuditCheckpointAuthenticator {
  String get authenticatorId;

  Future<Uint8List> authenticate(Uint8List payload);
}

/// Production checkpoint authentication. Key material never enters Dart: the
/// platform returns only HMAC-SHA256 bytes produced by Android Keystore or the
/// iOS Keychain-backed CryptoKit signer.
final class PlatformAuditCheckpointAuthenticator
    implements AuditCheckpointAuthenticator {
  const PlatformAuditCheckpointAuthenticator({
    MethodChannel channel = const MethodChannel('method.bluetooth'),
  }) : _channel = channel;

  final MethodChannel _channel;

  @override
  String get authenticatorId => 'platform-secure-hmac-sha256-v1';

  @override
  Future<Uint8List> authenticate(Uint8List payload) async {
    final result = await _channel.invokeMethod<Uint8List>(
      'auditCheckpointMac',
      <String, Object?>{'payload': payload},
    );
    if (result == null || result.length != 32) {
      throw StateError('Platform audit checkpoint authenticator unavailable.');
    }
    return Uint8List.fromList(result);
  }
}

/// Explicit deterministic authenticator for unit tests and offline tooling.
/// Production startup must inject [PlatformAuditCheckpointAuthenticator].
final class HmacAuditCheckpointAuthenticator
    implements AuditCheckpointAuthenticator {
  HmacAuditCheckpointAuthenticator({
    required Uint8List key,
    this.authenticatorId = 'deterministic-test-hmac-sha256-v1',
  }) : _key = Uint8List.fromList(key) {
    if (_key.length < 32) {
      throw ArgumentError.value(key.length, 'key', 'must be at least 32 bytes');
    }
    if (authenticatorId.trim().isEmpty) {
      throw ArgumentError.value(
        authenticatorId,
        'authenticatorId',
        'must not be empty',
      );
    }
  }

  factory HmacAuditCheckpointAuthenticator.forTests() =>
      HmacAuditCheckpointAuthenticator(
        key: Uint8List.fromList(
          sha256.convert(utf8.encode('hepta-audit-test-key-v1')).bytes,
        ),
      );

  final Uint8List _key;

  @override
  final String authenticatorId;

  @override
  Future<Uint8List> authenticate(Uint8List payload) async => Uint8List.fromList(
        Hmac(sha256, _key).convert(payload).bytes,
      );
}

bool constantTimeBytesEqual(List<int> left, List<int> right) {
  if (left.length != right.length) {
    return false;
  }
  var difference = 0;
  for (var index = 0; index < left.length; index++) {
    difference |= left[index] ^ right[index];
  }
  return difference == 0;
}
