import 'dart:convert';

import 'package:dio/dio.dart';

import 'canonical_json.dart';
import 'contracts.dart';

final class MutationAuthorizationRequest {
  MutationAuthorizationRequest({
    required this.taskId,
    required this.action,
    required Map<String, Object?> arguments,
    required this.riskTier,
    required this.deadline,
  }) : arguments = Map<String, Object?>.unmodifiable(arguments) {
    if (taskId.isEmpty ||
        taskId.length > 256 ||
        action.isEmpty ||
        action.length > 256 ||
        !deadline.isUtc) {
      throw ArgumentError('Invalid mutation authorization request.');
    }
    // Reject unsupported JSON values before an authority request is emitted.
    canonicalJson(this.arguments);
  }

  final String taskId;
  final String action;
  final Map<String, Object?> arguments;
  final RiskTier riskTier;
  final DateTime deadline;
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

abstract interface class MutationAuthorityProvider {
  Future<MutationAuthorization> authorize(
    MutationAuthorizationRequest request,
  );
}

final class FailClosedMutationAuthorityProvider
    implements MutationAuthorityProvider {
  const FailClosedMutationAuthorityProvider([this.reason = 'fail_closed']);

  final String reason;

  @override
  Future<MutationAuthorization> authorize(
    MutationAuthorizationRequest request,
  ) async =>
      MutationAuthorization(
        deviceId: 'unbound-device',
        context: const PolicyContext(
          subject: 'unauthenticated',
          authenticated: false,
          userPresent: false,
          biometricVerified: false,
          policyHash: 'unavailable',
        ),
        lease: null,
        source: reason,
      );
}

abstract interface class MutationAccessTokenProvider {
  Future<String?> getToken();
}

final class UnavailableMutationAccessTokenProvider
    implements MutationAccessTokenProvider {
  const UnavailableMutationAccessTokenProvider();

  @override
  Future<String?> getToken() async => null;
}

final class StaticMutationAccessTokenProvider
    implements MutationAccessTokenProvider {
  const StaticMutationAccessTokenProvider(this.token);

  final String? token;

  @override
  Future<String?> getToken() async => token;
}

/// Mutable only through authenticated application composition after login.
///
/// The registry contains a provider, never a cached bearer token. Logging out or
/// revoking the account must replace it with the unavailable provider.
final class MutationAccessTokenRegistry {
  MutationAccessTokenRegistry._();

  static MutationAccessTokenProvider _current =
      const UnavailableMutationAccessTokenProvider();

  static MutationAccessTokenProvider get current => _current;

  static void configure(MutationAccessTokenProvider provider) {
    _current = provider;
  }

  static void reset() {
    _current = const UnavailableMutationAccessTokenProvider();
  }
}

final class RegistryMutationAccessTokenProvider
    implements MutationAccessTokenProvider {
  const RegistryMutationAccessTokenProvider();

  @override
  Future<String?> getToken() => MutationAccessTokenRegistry.current.getToken();
}

final class HttpMutationAuthorityProvider
    implements MutationAuthorityProvider {
  HttpMutationAuthorityProvider({
    required Uri baseUri,
    required MutationAccessTokenProvider tokenProvider,
    Dio? dio,
    bool allowInsecureLoopback = false,
    DateTime Function()? clock,
  })  : _baseUri = _validatedUri(baseUri, allowInsecureLoopback),
        _tokenProvider = tokenProvider,
        _dio = dio ?? Dio(),
        _clock = clock ?? DateTime.now;

  final Uri _baseUri;
  final MutationAccessTokenProvider _tokenProvider;
  final Dio _dio;
  final DateTime Function() _clock;

  @override
  Future<MutationAuthorization> authorize(
    MutationAuthorizationRequest request,
  ) async {
    final now = _clock().toUtc();
    if (!request.deadline.isAfter(now)) {
      return _denied('mutation_authority_request_expired');
    }
    final token = await _tokenProvider.getToken();
    if (!_validBearer(token)) {
      return _denied('mutation_authority_unauthenticated');
    }
    final digest = sha256CanonicalJson(request.arguments);
    try {
      final response = await _dio.postUri<Object?>(
        _baseUri.resolve('v1/mutation/authorize'),
        data: <String, Object?>{
          'task_id': request.taskId,
          'action': request.action,
          'arguments': request.arguments,
          'risk_tier': request.riskTier.name,
          'deadline_epoch_seconds':
              request.deadline.microsecondsSinceEpoch ~/ Duration.microsecondsPerSecond,
        },
        options: Options(
          headers: <String, Object?>{
            'authorization': 'Bearer $token',
            'content-type': 'application/json',
            'accept': 'application/json',
          },
          sendTimeout: const Duration(seconds: 8),
          receiveTimeout: const Duration(seconds: 8),
          followRedirects: false,
          maxRedirects: 0,
          validateStatus: (int? status) => status == 200,
        ),
      );
      final body = response.data;
      if (body is! Map) {
        return _denied('mutation_authority_response_invalid');
      }
      return decodeAuthorization(
        body.cast<Object?, Object?>(),
        request: request,
        expectedArgumentDigest: digest,
        now: _clock().toUtc(),
      );
    } on DioException {
      return _denied('mutation_authority_unavailable');
    } on FormatException {
      return _denied('mutation_authority_response_invalid');
    } on ArgumentError {
      return _denied('mutation_authority_response_invalid');
    }
  }

  static MutationAuthorization decodeAuthorization(
    Map<Object?, Object?> body, {
    required MutationAuthorizationRequest request,
    required String expectedArgumentDigest,
    required DateTime now,
  }) {
    const fields = <String>{
      'task_id',
      'action',
      'risk_tier',
      'argument_digest',
      'subject',
      'device_id',
      'policy_hash',
      'authenticated',
      'user_present',
      'biometric_verified',
      'lease_id',
      'allowed_actions',
      'issued_at_epoch_seconds',
      'expires_at_epoch_seconds',
      'single_use',
    };
    if (body.keys.any((Object? key) => key is! String) ||
        body.keys.cast<String>().toSet() != fields) {
      throw const FormatException('mutation_authority_response_shape_invalid');
    }
    final taskId = body['task_id'];
    final action = body['action'];
    final riskTier = body['risk_tier'];
    final argumentDigest = body['argument_digest'];
    final subject = body['subject'];
    final deviceId = body['device_id'];
    final policyHash = body['policy_hash'];
    final authenticated = body['authenticated'];
    final userPresent = body['user_present'];
    final biometricVerified = body['biometric_verified'];
    final leaseId = body['lease_id'];
    final allowedActions = body['allowed_actions'];
    final issuedAtSeconds = body['issued_at_epoch_seconds'];
    final expiresAtSeconds = body['expires_at_epoch_seconds'];
    final singleUse = body['single_use'];

    if (taskId != request.taskId ||
        action != request.action ||
        riskTier != request.riskTier.name ||
        argumentDigest != expectedArgumentDigest ||
        subject is! String ||
        !_identifier.hasMatch(subject) ||
        deviceId is! String ||
        !_identifier.hasMatch(deviceId) ||
        policyHash is! String ||
        !_digest.hasMatch(policyHash) ||
        authenticated != true ||
        userPresent is! bool ||
        biometricVerified is! bool ||
        leaseId is! String ||
        !_identifier.hasMatch(leaseId) ||
        allowedActions is! List ||
        allowedActions.length != 1 ||
        allowedActions.single != request.action ||
        issuedAtSeconds is! int ||
        expiresAtSeconds is! int ||
        singleUse != true) {
      throw const FormatException('mutation_authority_response_binding_invalid');
    }
    final issuedAt = DateTime.fromMillisecondsSinceEpoch(
      issuedAtSeconds * Duration.millisecondsPerSecond,
      isUtc: true,
    );
    final expiresAt = DateTime.fromMillisecondsSinceEpoch(
      expiresAtSeconds * Duration.millisecondsPerSecond,
      isUtc: true,
    );
    final normalizedNow = now.toUtc();
    if (issuedAt.isAfter(normalizedNow.add(const Duration(seconds: 30))) ||
        !expiresAt.isAfter(normalizedNow) ||
        expiresAt.isAfter(request.deadline) ||
        !expiresAt.isAfter(issuedAt) ||
        (request.riskTier == RiskTier.r2 && !userPresent) ||
        (request.riskTier == RiskTier.r3 &&
            (!userPresent || !biometricVerified)) ||
        request.riskTier == RiskTier.r4) {
      throw const FormatException('mutation_authority_response_time_invalid');
    }

    final context = PolicyContext(
      subject: subject,
      authenticated: true,
      userPresent: userPresent,
      biometricVerified: biometricVerified,
      policyHash: policyHash,
    );
    final lease = DecisionLease(
      leaseId: leaseId,
      subject: subject,
      deviceId: deviceId,
      taskId: request.taskId,
      allowedActions: <String>{request.action},
      argumentConstraints: request.arguments,
      issuedAt: issuedAt,
      expiresAt: expiresAt,
      singleUse: true,
      policyHash: policyHash,
      approvalProof: 'identity-lease:$leaseId',
    );
    return MutationAuthorization(
      deviceId: deviceId,
      context: context,
      lease: lease,
      source: 'identity_https',
    );
  }

  MutationAuthorization _denied(String reason) => MutationAuthorization(
        deviceId: 'unbound-device',
        context: const PolicyContext(
          subject: 'unauthenticated',
          authenticated: false,
          userPresent: false,
          biometricVerified: false,
          policyHash: 'unavailable',
        ),
        lease: null,
        source: reason,
      );

  static bool _validBearer(String? value) =>
      value != null &&
      value.length >= 16 &&
      value.length <= 8192 &&
      value.codeUnits.every((int unit) => unit >= 33 && unit <= 126);

  static Uri _validatedUri(Uri uri, bool allowInsecureLoopback) {
    final loopback = <String>{'127.0.0.1', 'localhost', '::1'}.contains(uri.host);
    if (uri.userInfo.isNotEmpty || uri.fragment.isNotEmpty || uri.hasQuery) {
      throw ArgumentError.value(
        uri,
        'baseUri',
        'must not contain credentials, query or fragment',
      );
    }
    if (uri.scheme == 'https') {
      return uri;
    }
    if (allowInsecureLoopback && uri.scheme == 'http' && loopback) {
      return uri;
    }
    throw ArgumentError.value(
      uri,
      'baseUri',
      'must use HTTPS except explicit development loopback',
    );
  }

  static final RegExp _identifier =
      RegExp(r'^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$');
  static final RegExp _digest = RegExp(r'^[a-f0-9]{64}$');
}

final class MutationAuthorityRegistry {
  MutationAuthorityRegistry._();

  static MutationAuthorityProvider _current =
      const FailClosedMutationAuthorityProvider();

  static MutationAuthorityProvider get current => _current;

  static void configure(MutationAuthorityProvider provider) {
    _current = provider;
  }

  static void reset() {
    _current = const FailClosedMutationAuthorityProvider();
  }
}

final class MutationAuthorityBootstrap {
  MutationAuthorityBootstrap._();

  static void configureFromEnvironment() {
    const url = String.fromEnvironment('HEPTA_MUTATION_AUTHORITY_URL');
    const developmentToken =
        String.fromEnvironment('HEPTA_MUTATION_AUTHORITY_DEV_TOKEN');
    const product = bool.fromEnvironment('dart.vm.product');

    if (product && developmentToken.isNotEmpty) {
      MutationAuthorityRegistry.configure(
        const FailClosedMutationAuthorityProvider(
          'compiled_mutation_token_forbidden_in_product',
        ),
      );
      return;
    }
    if (url.isEmpty) {
      MutationAuthorityRegistry.reset();
      return;
    }
    final uri = Uri.tryParse(url);
    if (uri == null || !uri.hasScheme || uri.host.isEmpty) {
      MutationAuthorityRegistry.configure(
        const FailClosedMutationAuthorityProvider(
          'invalid_mutation_authority_url',
        ),
      );
      return;
    }
    final tokenProvider = !product && developmentToken.isNotEmpty
        ? const StaticMutationAccessTokenProvider(developmentToken)
        : const RegistryMutationAccessTokenProvider();
    try {
      MutationAuthorityRegistry.configure(
        HttpMutationAuthorityProvider(
          baseUri: uri,
          tokenProvider: tokenProvider,
          allowInsecureLoopback: !product,
        ),
      );
    } on ArgumentError {
      MutationAuthorityRegistry.configure(
        const FailClosedMutationAuthorityProvider(
          'insecure_mutation_authority_url',
        ),
      );
    }
  }
}
