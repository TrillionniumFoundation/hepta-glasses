import 'canonical_json.dart';
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
