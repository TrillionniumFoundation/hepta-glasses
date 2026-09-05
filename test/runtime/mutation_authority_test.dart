import 'package:demo_ai_even/runtime/clock.dart';
import 'package:demo_ai_even/runtime/contracts.dart';
import 'package:demo_ai_even/runtime/mutation_authority.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/test_mutation_authority.dart';

void main() {
  final now = DateTime.utc(2026, 9, 1, 12);

  MutationAuthorizationRequest request({
    DateTime? deadline,
  }) =>
      MutationAuthorizationRequest(
        taskId: 'task-1',
        action: 'device.display_text',
        arguments: const <String, Object?>{'text': 'hello'},
        riskTier: RiskTier.r1,
        deadline: deadline ?? now.add(const Duration(minutes: 1)),
      );

  test('default authority is unauthenticated and cannot mint a lease',
      () async {
    const provider = FailClosedMutationAuthorityProvider();

    final authorization = await provider.authorize(request());

    expect(authorization.context.authenticated, isFalse);
    expect(authorization.context.userPresent, isFalse);
    expect(authorization.lease, isNull);
    expect(authorization.deviceId, 'unbound-device');
    expect(authorization.source, 'fail_closed');
  });

  test('test authority rejects incomplete bindings', () {
    expect(
      () => TestMutationAuthorityProvider(
        subject: '',
        deviceId: 'test-device',
        policyHash: 'test-policy',
      ),
      throwsArgumentError,
    );
  });

  test('test lease is exactly task action argument and device bound', () async {
    final provider = TestMutationAuthorityProvider(
      subject: 'test-subject',
      deviceId: 'test-device',
      policyHash: 'test-policy',
      clock: MutableClock(now),
    );

    final authorization = await provider.authorize(request());
    final lease = authorization.lease;

    expect(authorization.context.authenticated, isTrue);
    expect(authorization.context.userPresent, isTrue);
    expect(authorization.deviceId, 'test-device');
    expect(authorization.source, 'test_only');
    expect(lease, isNotNull);
    expect(lease!.taskId, 'task-1');
    expect(lease.deviceId, 'test-device');
    expect(lease.allowedActions, <String>{'device.display_text'});
    expect(lease.argumentConstraints, const <String, Object?>{'text': 'hello'});
    expect(lease.singleUse, isTrue);
    expect(lease.policyHash, 'test-policy');
    expect(lease.approvalProof, 'test-only-authority');
  });

  test('test lease never exceeds the request deadline', () async {
    final deadline = now.add(const Duration(seconds: 3));
    final provider = TestMutationAuthorityProvider(
      subject: 'test-subject',
      deviceId: 'test-device',
      policyHash: 'test-policy',
      clock: MutableClock(now),
      leaseTtl: const Duration(minutes: 1),
    );

    final authorization = await provider.authorize(
      request(deadline: deadline),
    );

    expect(authorization.lease!.expiresAt, deadline);
  });
}
