import 'clock.dart';
import 'contracts.dart';

final class PolicyEngine {
  PolicyEngine({Clock clock = const SystemClock()}) : _clock = clock;

  final Clock _clock;
  final Set<String> _consumedLeaseIds = <String>{};

  PolicyDecision evaluate({
    required ToolSpec spec,
    required ToolRequest request,
    required PolicyContext context,
    DecisionLease? lease,
  }) {
    if (!context.authenticated) {
      return const PolicyDecision(
        allowed: false,
        reason: 'caller_not_authenticated',
      );
    }
    if (spec.action != request.action ||
        spec.riskTier != request.riskTier ||
        spec.mutating != request.mutating) {
      return const PolicyDecision(
        allowed: false,
        reason: 'tool_contract_mismatch',
      );
    }
    if (spec.riskTier == RiskTier.r4) {
      return const PolicyDecision(
        allowed: false,
        reason: 'r4_disabled_in_consumer_profile',
      );
    }
    if (!spec.mutating &&
        (spec.riskTier == RiskTier.r0 || spec.riskTier == RiskTier.r1)) {
      return const PolicyDecision(allowed: true, reason: 'read_only_allowed');
    }
    if (lease == null) {
      return const PolicyDecision(
        allowed: false,
        reason: 'decision_lease_required',
      );
    }
    if (_consumedLeaseIds.contains(lease.leaseId)) {
      return const PolicyDecision(
        allowed: false,
        reason: 'decision_lease_already_consumed',
      );
    }
    final now = _clock.now();
    if (lease.issuedAt.isAfter(now)) {
      return const PolicyDecision(
        allowed: false,
        reason: 'decision_lease_not_yet_valid',
      );
    }
    if (!now.isBefore(lease.expiresAt)) {
      return const PolicyDecision(
        allowed: false,
        reason: 'decision_lease_expired',
      );
    }
    if (lease.subject != context.subject ||
        lease.taskId != request.taskId ||
        lease.deviceId != request.deviceId ||
        !lease.allowedActions.contains(request.action) ||
        lease.policyHash != context.policyHash) {
      return const PolicyDecision(
        allowed: false,
        reason: 'decision_lease_binding_mismatch',
      );
    }
    if (lease.argumentDigest != request.argumentDigest) {
      return const PolicyDecision(
        allowed: false,
        reason: 'decision_lease_argument_mismatch',
      );
    }
    if (request.origin == TrustClass.untrusted) {
      if (request.humanConfirmationDigest == null) {
        return const PolicyDecision(
          allowed: false,
          reason: 'untrusted_content_cannot_authorize_mutation',
        );
      }
      if (request.humanConfirmationDigest != request.argumentDigest) {
        return const PolicyDecision(
          allowed: false,
          reason: 'confirmation_digest_mismatch',
        );
      }
    }
    if (spec.riskTier == RiskTier.r2 && !context.userPresent) {
      return const PolicyDecision(
        allowed: false,
        reason: 'user_presence_required',
      );
    }
    if (spec.riskTier == RiskTier.r3 &&
        (!context.userPresent || !context.biometricVerified)) {
      return const PolicyDecision(
        allowed: false,
        reason: 'biometric_confirmation_required',
      );
    }
    return const PolicyDecision(allowed: true, reason: 'lease_authorized');
  }

  void consume(DecisionLease? lease) {
    if (lease != null && lease.singleUse) {
      _consumedLeaseIds.add(lease.leaseId);
    }
  }

  void restoreConsumed(Iterable<String> leaseIds) {
    _consumedLeaseIds.addAll(leaseIds);
  }

  bool isConsumed(String leaseId) => _consumedLeaseIds.contains(leaseId);
}
