import 'package:demo_ai_even/runtime/audit_journal.dart';
import 'package:demo_ai_even/runtime/clock.dart';
import 'package:demo_ai_even/runtime/contracts.dart';
import 'package:demo_ai_even/runtime/policy_engine.dart';
import 'package:demo_ai_even/runtime/tool_gateway.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  final now = DateTime.utc(2026, 9, 1, 12);
  late MutableClock clock;
  late InMemoryAuditJournal journal;
  late ToolGateway gateway;

  ToolRequest request(String key) => ToolRequest(
        requestId: 'request-$key',
        taskId: 'task-1',
        deviceId: 'device-1',
        action: 'device.test',
        arguments: const <String, Object?>{'value': 1},
        riskTier: RiskTier.r1,
        mutating: true,
        idempotencyKey: key,
        deadline: now.add(const Duration(minutes: 1)),
        origin: TrustClass.user,
      );

  PolicyContext context() => const PolicyContext(
        subject: 'user-1',
        authenticated: true,
        userPresent: true,
        biometricVerified: false,
        policyHash: 'policy-1',
      );

  DecisionLease lease(ToolRequest request) => DecisionLease(
        leaseId: 'lease-${request.idempotencyKey}',
        subject: 'user-1',
        taskId: request.taskId,
        deviceId: request.deviceId,
        allowedActions: <String>{request.action},
        argumentConstraints: request.arguments,
        issuedAt: now,
        expiresAt: now.add(const Duration(minutes: 1)),
        singleUse: true,
        policyHash: 'policy-1',
        approvalProof: 'test-user-presence',
      );

  setUp(() {
    clock = MutableClock(now);
    journal = InMemoryAuditJournal(clock: clock);
    gateway = ToolGateway(
      journal: journal,
      policy: PolicyEngine(clock: clock),
      clock: clock,
    );
  });

  test('pre-write rejection is failed but retry-safe and not indeterminate',
      () async {
    gateway.register(
      const ToolSpec(
        action: 'device.test',
        riskTier: RiskTier.r1,
        mutating: true,
      ),
      (_) async => throw const RejectedToolEffect(
        'side_disconnected',
        externalId: 'effect-1',
      ),
    );
    final toolRequest = request('safe-reject');

    final receipt = await gateway.execute(
      request: toolRequest,
      context: context(),
      lease: lease(toolRequest),
    );

    expect(receipt.status, ToolReceiptStatus.failed);
    expect(receipt.result['error'], 'tool_effect_rejected_before_write');
    expect(receipt.result['error_code'], 'side_disconnected');
    expect(receipt.result['retry_safe'], isTrue);
    expect(receipt.result['effect_may_have_occurred'], isFalse);
    expect((await journal.readAll()).last.eventType, 'tool.failed');
  });

  test('uncertain effect requires reconciliation and is never retry-safe',
      () async {
    gateway.register(
      const ToolSpec(
        action: 'device.test',
        riskTier: RiskTier.r1,
        mutating: true,
      ),
      (_) async => throw const IndeterminateToolEffect(
        'effect-2',
        code: 'ack_timeout_after_native_write',
      ),
      reconciler: (_, externalId) async => <String, Object?>{
        'authoritative': false,
        'external_id': externalId,
      },
    );
    final toolRequest = request('uncertain');

    final receipt = await gateway.execute(
      request: toolRequest,
      context: context(),
      lease: lease(toolRequest),
    );

    expect(receipt.status, ToolReceiptStatus.indeterminate);
    expect(receipt.result['error_code'], 'ack_timeout_after_native_write');
    expect(receipt.result['retry_safe'], isFalse);
    expect(receipt.result['effect_may_have_occurred'], isTrue);
    expect((await journal.readAll()).last.eventType, 'tool.indeterminate');
  });

  test('typed certainty survives metadata-only journal recovery', () async {
    gateway.register(
      const ToolSpec(
        action: 'device.test',
        riskTier: RiskTier.r1,
        mutating: true,
      ),
      (_) async => throw const RejectedToolEffect('native_write_not_accepted'),
    );
    final toolRequest = request('recover-safe-reject');
    await gateway.execute(
      request: toolRequest,
      context: context(),
      lease: lease(toolRequest),
    );

    final recovered = ToolGateway(
      journal: journal,
      policy: PolicyEngine(clock: clock),
      clock: clock,
    );
    recovered.register(
      const ToolSpec(
        action: 'device.test',
        riskTier: RiskTier.r1,
        mutating: true,
      ),
      (_) async => const <String, Object?>{},
    );
    await recovered.recover();

    final receipt = recovered.receiptFor('recover-safe-reject');
    expect(receipt, isNotNull);
    expect(receipt!.result['retry_safe'], isTrue);
    expect(receipt.result['effect_may_have_occurred'], isFalse);
    expect(receipt.result['error_code'], 'native_write_not_accepted');
  });
}
