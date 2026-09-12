import 'dart:convert';
import 'dart:io';

import 'package:hepta_glasses/runtime/canonical_json.dart';
import 'package:hepta_glasses/runtime/contracts.dart';
import 'package:hepta_glasses/runtime/mutation_authority.dart';
import 'package:flutter_test/flutter_test.dart';

Map<String, Object?> _stringMap(Object? value) =>
    Map<String, Object?>.from(value! as Map);

Map<Object?, Object?> _responseCopy(Map<String, Object?> contract) {
  final encoded = jsonEncode(contract['expected_response']);
  return Map<Object?, Object?>.from(jsonDecode(encoded) as Map);
}

void main() {
  const contractPath = 'contracts/conformance/mutation-authority-v1.json';
  final contractText = File(contractPath).readAsStringSync();
  final contract = jsonDecode(contractText) as Map<String, Object?>;
  final requestJson = _stringMap(contract['request']);
  final principalJson = _stringMap(contract['principal']);
  final arguments = _stringMap(requestJson['arguments']);
  final leaseComponent = contract['lease_token_component']! as String;
  final nowSeconds = contract['now_epoch_seconds']! as int;
  final deadlineSeconds = requestJson['deadline_epoch_seconds']! as int;
  final now = DateTime.fromMillisecondsSinceEpoch(
    nowSeconds * Duration.millisecondsPerSecond,
    isUtc: true,
  );
  final request = MutationAuthorizationRequest(
    taskId: requestJson['task_id']! as String,
    action: requestJson['action']! as String,
    arguments: arguments,
    riskTier: riskTierFromJson(requestJson['risk_tier']! as String),
    deadline: DateTime.fromMillisecondsSinceEpoch(
      deadlineSeconds * Duration.millisecondsPerSecond,
      isUtc: true,
    ),
  );

  test('Dart consumes the server mutation-authority identity vector', () {
    expect(
      contract['contract_id'],
      'hepta-mutation-authority-conformance-v1',
    );
    expect(contract['schema_version'], 1);
    final expectedDigest = contract['expected_argument_digest']! as String;
    expect(sha256CanonicalJson(arguments), expectedDigest);

    final authorization = HttpMutationAuthorityProvider.decodeAuthorization(
      _responseCopy(contract),
      request: request,
      expectedArgumentDigest: expectedDigest,
      now: now,
    );
    final lease = authorization.lease!;

    expect(authorization.source, 'identity_https');
    expect(authorization.deviceId, principalJson['device_id']);
    expect(authorization.context.subject, principalJson['subject']);
    expect(authorization.context.authenticated, isTrue);
    expect(authorization.context.userPresent, principalJson['user_present']);
    expect(
      authorization.context.biometricVerified,
      principalJson['biometric_verified'],
    );
    expect(authorization.context.policyHash, principalJson['policy_hash']);
    expect(lease.leaseId, 'l-$leaseComponent');
    expect(lease.taskId, request.taskId);
    expect(lease.deviceId, principalJson['device_id']);
    expect(lease.allowedActions, <String>{request.action});
    expect(lease.argumentConstraints, arguments);
    expect(lease.argumentDigest, expectedDigest);
    expect(lease.singleUse, isTrue);
    expect(lease.policyHash, principalJson['policy_hash']);
    expect(lease.approvalProof, 'identity-lease:${lease.leaseId}');
    expect(lease.issuedAt, now);
    expect(lease.expiresAt, request.deadline);
  });

  test('mobile decoder rejects authority-vector field drift', () {
    final expectedDigest = contract['expected_argument_digest']! as String;
    final zeroDigest = List<String>.filled(64, '0').join();
    final mutations = <String, void Function(Map<Object?, Object?>)>{
      'extra-field': (body) {
        body['extra'] = true;
      },
      'task': (body) {
        body['task_id'] = 'other';
      },
      'action': (body) {
        body['action'] = 'other';
      },
      'risk': (body) {
        body['risk_tier'] = 'r2';
      },
      'digest': (body) {
        body['argument_digest'] = zeroDigest;
      },
      'subject': (body) {
        body['subject'] = 'bad/value';
      },
      'device': (body) {
        body['device_id'] = '';
      },
      'policy': (body) {
        body['policy_hash'] = 'short';
      },
      'authentication': (body) {
        body['authenticated'] = false;
      },
      'actions': (body) {
        body['allowed_actions'] = <String>['different'];
      },
      'single-use': (body) {
        body['single_use'] = false;
      },
      'expiry': (body) {
        body['expires_at_epoch_seconds'] = deadlineSeconds + 1;
      },
    };

    for (final mutation in mutations.entries) {
      final body = _responseCopy(contract);
      mutation.value(body);
      expect(
        () => HttpMutationAuthorityProvider.decodeAuthorization(
          body,
          request: request,
          expectedArgumentDigest: expectedDigest,
          now: now,
        ),
        throwsFormatException,
        reason: mutation.key,
      );
    }
  });
}
