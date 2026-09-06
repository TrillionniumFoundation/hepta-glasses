import 'package:demo_ai_even/runtime/clock.dart';
import 'package:demo_ai_even/runtime/contracts.dart';
import 'package:demo_ai_even/runtime/mutation_authority.dart';

/// Test-only authority for deterministic policy and lease tests.
///
/// This file is outside `lib/`, is never imported by product code, and must be
/// absent from every Android and iOS release artifact.
final class TestMutationAuthorityProvider implements MutationAuthorityProvider {
  TestMutationAuthorityProvider({
    required this.subject,
    required this.deviceId,
    required this.policyHash,
    Clock clock = const SystemClock(),
    this.leaseTtl = const Duration(seconds: 20),
  }) : _clock = clock {
    if (subject.trim().isEmpty ||
        deviceId.trim().isEmpty ||
        policyHash.trim().isEmpty) {
      throw ArgumentError('Test authority bindings must not be empty.');
    }
    if (leaseTtl <= Duration.zero) {
      throw ArgumentError.value(leaseTtl, 'leaseTtl', 'must be positive');
    }
  }

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
        source: 'test_expired',
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
        leaseId: 'test-lease-${now.microsecondsSinceEpoch}-$nonce',
        subject: subject,
        taskId: request.taskId,
        deviceId: deviceId,
        allowedActions: <String>{request.action},
        argumentConstraints: request.arguments,
        issuedAt: now,
        expiresAt: expiry,
        singleUse: true,
        policyHash: policyHash,
        approvalProof: 'test-only-authority',
      ),
      source: 'test_only',
    );
  }
}
