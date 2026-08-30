import 'package:demo_ai_even/runtime/canonical_json.dart';
import 'package:demo_ai_even/runtime/clock.dart';
import 'package:demo_ai_even/runtime/contracts.dart';
import 'package:demo_ai_even/runtime/policy_engine.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  final now = DateTime.utc(2026, 8, 30);
  late MutableClock clock;
  late PolicyEngine policy;
  late PolicyContext context;

  setUp(() {
    clock = MutableClock(now);
    policy = PolicyEngine(clock: clock);
    context = const PolicyContext(
      subject: 'user-1',
      authenticated: true,
      userPresent: true,
      biometricVerified: false,
      policyHash: 'policy-v1',
    );
  });

  test('authenticated R0 read is allowed without a lease', () {
    final request = ToolRequest(
      requestId: 'r-1',
      taskId: 't-1',
      deviceId: 'g-1',
      action: 'device.get_state',
      arguments: const <String, Object?>{},
      riskTier: RiskTier.r0,
      mutating: false,
      idempotencyKey: 'read-1',
      deadline: now.add(const Duration(minutes: 1)),
    );
    final decision = policy.evaluate(
      spec: const ToolSpec(
        action: 'device.get_state',
        riskTier: RiskTier.r0,
        mutating: false,
      ),
      request: request,
      context: context,
    );
    expect(decision.allowed, isTrue);
  });

  test('R2 mutation requires and consumes a bound single-use lease', () {
    final request = ToolRequest(
      requestId: 'r-2',
      taskId: 't-1',
      deviceId: 'g-1',
      action: 'reminder.commit',
      arguments: const <String, Object?>{'title': 'Stand up'},
      riskTier: RiskTier.r2,
      mutating: true,
      idempotencyKey: 'mutation-1',
      deadline: now.add(const Duration(minutes: 1)),
    );
    final lease = DecisionLease(
      leaseId: 'lease-1',
      subject: 'user-1',
      taskId: 't-1',
      deviceId: 'g-1',
      allowedActions: const <String>{'reminder.commit'},
      argumentDigest: sha256CanonicalJson(request.arguments),
      expiresAt: now.add(const Duration(minutes: 1)),
      singleUse: true,
      policyHash: 'policy-v1',
    );
    const spec = ToolSpec(
      action: 'reminder.commit',
      riskTier: RiskTier.r2,
      mutating: true,
    );

    expect(
      policy.evaluate(
        spec: spec,
        request: request,
        context: context,
        lease: lease,
      ).allowed,
      isTrue,
    );
    policy.consume(lease);
    expect(
      policy.evaluate(
        spec: spec,
        request: request,
        context: context,
        lease: lease,
      ).reason,
      'decision_lease_already_consumed',
    );
  });

  test('mutation lease is rejected when exact arguments drift', () {
    const approvedArguments = <String, Object?>{'title': 'Stand up'};
    final request = ToolRequest(
      requestId: 'r-3',
      taskId: 't-1',
      deviceId: 'g-1',
      action: 'reminder.commit',
      arguments: const <String, Object?>{'title': 'Different'},
      riskTier: RiskTier.r2,
      mutating: true,
      idempotencyKey: 'mutation-2',
      deadline: now.add(const Duration(minutes: 1)),
    );
    final lease = DecisionLease(
      leaseId: 'lease-2',
      subject: 'user-1',
      taskId: 't-1',
      deviceId: 'g-1',
      allowedActions: const <String>{'reminder.commit'},
      argumentDigest: sha256CanonicalJson(approvedArguments),
      expiresAt: now.add(const Duration(minutes: 1)),
      singleUse: true,
      policyHash: 'policy-v1',
    );
    final decision = policy.evaluate(
      spec: const ToolSpec(
        action: 'reminder.commit',
        riskTier: RiskTier.r2,
        mutating: true,
      ),
      request: request,
      context: context,
      lease: lease,
    );
    expect(decision.reason, 'decision_lease_binding_mismatch');
  });

  test('R4 is denied even with a lease', () {
    final request = ToolRequest(
      requestId: 'r-4',
      taskId: 't-1',
      deviceId: 'g-1',
      action: 'firmware.write',
      arguments: const <String, Object?>{},
      riskTier: RiskTier.r4,
      mutating: true,
      idempotencyKey: 'r4',
      deadline: now.add(const Duration(minutes: 1)),
    );
    final decision = policy.evaluate(
      spec: const ToolSpec(
        action: 'firmware.write',
        riskTier: RiskTier.r4,
        mutating: true,
      ),
      request: request,
      context: context,
    );
    expect(decision.reason, 'r4_disabled_in_consumer_profile');
  });
}
