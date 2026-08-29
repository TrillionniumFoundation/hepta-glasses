import 'package:demo_ai_even/runtime/audit_journal.dart';
import 'package:demo_ai_even/runtime/clock.dart';
import 'package:demo_ai_even/runtime/contracts.dart';
import 'package:demo_ai_even/runtime/policy_engine.dart';
import 'package:demo_ai_even/runtime/tool_gateway.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('mutation is journaled before effect and replayed once', () async {
    final now = DateTime.utc(2026, 8, 30);
    final clock = MutableClock(now);
    final journal = InMemoryAuditJournal(clock: clock);
    final policy = PolicyEngine(clock: clock);
    final gateway = ToolGateway(journal: journal, policy: policy, clock: clock);
    var effects = 0;
    gateway.register(
      const ToolSpec(
        action: 'display.show_card',
        riskTier: RiskTier.r1,
        mutating: true,
      ),
      (ToolRequest request) async {
        effects++;
        return <String, Object?>{'displayed': true};
      },
    );

    final request = ToolRequest(
      requestId: 'request-1',
      taskId: 'task-1',
      deviceId: 'device-1',
      action: 'display.show_card',
      arguments: const <String, Object?>{'card_id': 'card-1'},
      riskTier: RiskTier.r1,
      mutating: true,
      idempotencyKey: 'display-card-1',
      deadline: now.add(const Duration(minutes: 1)),
    );
    final lease = DecisionLease(
      leaseId: 'lease-1',
      subject: 'user-1',
      taskId: 'task-1',
      deviceId: 'device-1',
      allowedActions: const <String>{'display.show_card'},
      expiresAt: now.add(const Duration(minutes: 1)),
      singleUse: true,
      policyHash: 'policy-v1',
    );
    const context = PolicyContext(
      subject: 'user-1',
      authenticated: true,
      userPresent: true,
      biometricVerified: false,
      policyHash: 'policy-v1',
    );

    final first = await gateway.execute(
      request: request,
      context: context,
      lease: lease,
    );
    final replay = await gateway.execute(
      request: request,
      context: context,
      lease: lease,
    );

    expect(first.status, ToolReceiptStatus.succeeded);
    expect(replay.replayed, isTrue);
    expect(effects, 1);
    final events = (await journal.readAll())
        .map((AuditEntry entry) => entry.eventType)
        .toList();
    expect(events.indexOf('tool.prepared'), lessThan(events.indexOf('tool.completed')));
  });

  test('unknown tool fails closed without invoking an effect', () async {
    final now = DateTime.utc(2026, 8, 30);
    final clock = MutableClock(now);
    final gateway = ToolGateway(
      journal: InMemoryAuditJournal(clock: clock),
      policy: PolicyEngine(clock: clock),
      clock: clock,
    );
    final receipt = await gateway.execute(
      request: ToolRequest(
        requestId: 'request-2',
        taskId: 'task-1',
        deviceId: 'device-1',
        action: 'unknown',
        arguments: const <String, Object?>{},
        riskTier: RiskTier.r0,
        mutating: false,
        idempotencyKey: 'unknown-1',
        deadline: now.add(const Duration(minutes: 1)),
      ),
      context: const PolicyContext(
        subject: 'user-1',
        authenticated: true,
        userPresent: true,
        biometricVerified: false,
        policyHash: 'policy-v1',
      ),
    );
    expect(receipt.status, ToolReceiptStatus.rejected);
    expect(receipt.policyReason, 'tool_not_registered');
  });
}
