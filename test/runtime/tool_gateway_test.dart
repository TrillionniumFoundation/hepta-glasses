import 'package:demo_ai_even/runtime/audit_journal.dart';
import 'package:demo_ai_even/runtime/clock.dart';
import 'package:demo_ai_even/runtime/contracts.dart';
import 'package:demo_ai_even/runtime/policy_engine.dart';
import 'package:demo_ai_even/runtime/tool_gateway.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  final now = DateTime.utc(2026, 8, 30);

  ToolRequest displayRequest({String idempotencyKey = 'display-card-1'}) =>
      ToolRequest(
        requestId: 'request-1',
        taskId: 'task-1',
        deviceId: 'device-1',
        action: 'display.show_card',
        arguments: const <String, Object?>{'card_id': 'card-1'},
        riskTier: RiskTier.r1,
        mutating: true,
        idempotencyKey: idempotencyKey,
        deadline: now.add(const Duration(minutes: 1)),
      );

  DecisionLease displayLease(ToolRequest request, {String id = 'lease-1'}) =>
      DecisionLease(
        leaseId: id,
        subject: 'user-1',
        taskId: request.taskId,
        deviceId: request.deviceId,
        allowedActions: <String>{request.action},
        argumentConstraints: request.arguments,
        issuedAt: now,
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

  test('mutation is journaled before effect and replayed once', () async {
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

    final request = displayRequest();
    final lease = displayLease(request);
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

  test('terminal receipt survives gateway restart without duplicate effect',
      () async {
    final clock = MutableClock(now);
    final journal = InMemoryAuditJournal(clock: clock);
    var effects = 0;

    ToolGateway buildGateway() {
      final gateway = ToolGateway(
        journal: journal,
        policy: PolicyEngine(clock: clock),
        clock: clock,
      );
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
      return gateway;
    }

    final request = displayRequest();
    final firstGateway = buildGateway();
    await firstGateway.execute(
      request: request,
      context: context,
      lease: displayLease(request),
    );

    final recoveredGateway = buildGateway();
    await recoveredGateway.recover();
    final replay = await recoveredGateway.execute(
      request: request,
      context: context,
      lease: displayLease(request, id: 'replacement-lease'),
    );

    expect(replay.replayed, isTrue);
    expect(replay.status, ToolReceiptStatus.succeeded);
    expect(effects, 1);
  });

  test('indeterminate effect is cached and resolved only by reconciler',
      () async {
    final clock = MutableClock(now);
    final journal = InMemoryAuditJournal(clock: clock);
    final gateway = ToolGateway(
      journal: journal,
      policy: PolicyEngine(clock: clock),
      clock: clock,
    );
    var executions = 0;
    var reconciliations = 0;
    gateway.register(
      const ToolSpec(
        action: 'display.show_card',
        riskTier: RiskTier.r1,
        mutating: true,
      ),
      (ToolRequest request) async {
        executions++;
        throw const IndeterminateToolEffect('display:external-1');
      },
      reconciler: (ToolRequest request, String externalId) async {
        reconciliations++;
        return <String, Object?>{
          'authoritative': true,
          'external_id': externalId,
          'displayed': true,
        };
      },
    );

    final request = displayRequest(idempotencyKey: 'display-indeterminate');
    final first = await gateway.execute(
      request: request,
      context: context,
      lease: displayLease(request, id: 'lease-indeterminate'),
    );
    final replay = await gateway.execute(
      request: request,
      context: context,
      lease: displayLease(request, id: 'unused-replay-lease'),
    );
    final reconciled = await gateway.reconcile(
      idempotencyKey: request.idempotencyKey,
    );

    expect(first.status, ToolReceiptStatus.indeterminate);
    expect(replay.replayed, isTrue);
    expect(reconciled.status, ToolReceiptStatus.succeeded);
    expect(executions, 1);
    expect(reconciliations, 1);
  });

  test('prepared entry without terminal recovers as indeterminate', () async {
    final clock = MutableClock(now);
    final journal = InMemoryAuditJournal(clock: clock);
    final request = displayRequest(idempotencyKey: 'crash-window');
    await journal.append('tool.prepared', <String, Object?>{
      'request': request.toJson(),
      'request_fingerprint': request.fingerprint,
      'lease_id': 'lease-crash',
      'started_at': now.toIso8601String(),
    });

    final policy = PolicyEngine(clock: clock);
    final gateway = ToolGateway(journal: journal, policy: policy, clock: clock);
    await gateway.recover();

    expect(
      gateway.receiptFor(request.idempotencyKey)?.status,
      ToolReceiptStatus.indeterminate,
    );
    expect(policy.isConsumed('lease-crash'), isTrue);
  });

  test('unknown tool fails closed without invoking an effect', () async {
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
      context: context,
    );
    expect(receipt.status, ToolReceiptStatus.rejected);
    expect(receipt.policyReason, 'tool_not_registered');
  });
}
