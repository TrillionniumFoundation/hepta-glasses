import 'canonical_json.dart';
import 'clock.dart';
import 'contracts.dart';

final class MutationAuthorizationRequest {
  MutationAuthorizationRequest({
    required this.taskId,
    required this.action,
    required Map<String, Object?> arguments,
    required this.riskTier,
    required DateTime deadline,
  })  : arguments = Map<String, Object?>.unmodifiable(arguments),
        deadline = deadline.toUtc();

  final String taskId;
  final String action;
  final Map<String, Object?> arguments;
  final RiskTier riskTier;
  final DateTime deadline;

  String get argumentDigest => sha256CanonicalJson(arguments);
}

final class MutationAuthorization {
  const MutationAuthorization({
    required this.deviceId,
    required this.context,
    required this.lease,
    required this.source,
  });

  final String deviceId;
  final PolicyContext context;
  final DecisionLease? lease;
  final String source;
}

/// Supplies authentication, user-presence, device identity, and lease proof.
/// HeptaRuntime deliberately cannot synthesize any of these claims itself.
abstract interface class MutationAuthorityProvider {
  Future<MutationAuthorization> authorize(
    MutationAuthorizationRequest request,
  );
}

/// Production-safe default while identity/attestation infrastructure is absent.
/// Requests still reach PolicyEngine and are durably rejected as unauthenticated.
final class FailClosedMutationAuthorityProvider
    implements MutationAuthorityProvider {
  const FailClosedMutationAuthorityProvider({
    this.deviceId = 'unbound-device',
    this.policyHash = 'authority-unavailable',
  });

  final String deviceId;
  final String policyHash;

  @override
  Future<MutationAuthorization> authorize(
    MutationAuthorizationRequest request,
  ) async =>
      MutationAuthorization(
        deviceId: deviceId,
        context: PolicyContext(
          subject: 'unauthenticated',
          authenticated: false,
          userPresent: false,
          biometricVerified: false,
          policyHash: policyHash,
        ),
        lease: null,
        source: 'fail_closed',
      );
}

/// Explicit development-only authority adapter. It is not selected unless the
/// application is built with HEPTA_ALLOW_DEVELOPMENT_AUTHORITY=true. Production
/// builds must replace it with control-plane/attestation-backed authority.
final class DevelopmentMutationAuthorityProvider
    implements MutationAuthorityProvider {
  DevelopmentMutationAuthorityProvider({
    required bool enabled,
    required this.subject,
    required this.deviceId,
    required this.policyHash,
    Clock clock = const SystemClock(),
    this.leaseTtl = const Duration(seconds: 20),
  })  : _clock = clock,
        _enabled = enabled {
    if (!enabled) {
      throw StateError(
        'Development mutation authority requires an explicit build flag.',
      );
    }
    if (subject.trim().isEmpty ||
        deviceId.trim().isEmpty ||
        policyHash.trim().isEmpty) {
      throw ArgumentError('Development authority bindings must not be empty.');
    }
    if (leaseTtl <= Duration.zero) {
      throw ArgumentError.value(leaseTtl, 'leaseTtl', 'must be positive');
    }
  }

  final bool _enabled;
  final String subject;
  final String deviceId;
  final String policyHash;
  final Clock _clock;
  final Duration leaseTtl;
  int _nonce = 0;

  @override
  Future<MutationAuthorization> authorize(
    MutationAuthorizationRequest request,
  ) async {
    if (!_enabled) {
      throw StateError('Development mutation authority is disabled.');
    }
    final now = _clock.now().toUtc();
    final requestedExpiry = now.add(leaseTtl);
    final expiry = requestedExpiry.isBefore(request.deadline)
        ? requestedExpiry
        : request.deadline;
    if (!now.isBefore(expiry)) {
      return MutationAuthorization(
        deviceId: deviceId,
        context: PolicyContext(
          subject: subject,
          authenticated: true,
          userPresent: false,
          biometricVerified: false,
          policyHash: policyHash,
        ),
        lease: null,
        source: 'development_expired',
      );
    }
    final nonce = ++_nonce;
    return MutationAuthorization(
      deviceId: deviceId,
      context: PolicyContext(
        subject: subject,
        authenticated: true,
        userPresent: true,
        biometricVerified: false,
        policyHash: policyHash,
      ),
      lease: DecisionLease(
        leaseId: 'dev-lease-${now.microsecondsSinceEpoch}-$nonce',
        subject: subject,
        taskId: request.taskId,
        deviceId: deviceId,
        allowedActions: <String>{request.action},
        argumentConstraints: request.arguments,
        issuedAt: now,
        expiresAt: expiry,
        singleUse: true,
        policyHash: policyHash,
        approvalProof: 'explicit-development-build-flag',
      ),
      source: 'development_build_flag',
    );
  }
}
