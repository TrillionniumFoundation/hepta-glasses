part of 'mutation_authority.dart';

final class HttpMutationAuthorityProvider implements MutationAuthorityProvider {
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

  static const int maxResponseBytes = 64 * 1024;

  final Uri _baseUri;
  final MutationAccessTokenProvider _tokenProvider;
  final Dio _dio;
  final DateTime Function() _clock;

  @override
  Future<MutationAuthorization> authorize(
    MutationAuthorizationRequest request,
  ) async {
    try {
      final now = _clock().toUtc();
      if (!request.deadline.isAfter(now)) {
        return _denied('mutation_authority_request_expired');
      }
      final token = await _tokenProvider.getToken();
      if (!_validBearer(token)) {
        return _denied('mutation_authority_unauthenticated');
      }
      final digest = sha256CanonicalJson(request.arguments);
      final response = await _dio.postUri<ResponseBody>(
        _baseUri.resolve('v1/mutation/authorize'),
        data: <String, Object?>{
          'task_id': request.taskId,
          'action': request.action,
          'arguments': request.arguments,
          'risk_tier': request.riskTier.name,
          'deadline_epoch_seconds': request.deadline.microsecondsSinceEpoch ~/
              Duration.microsecondsPerSecond,
        },
        options: Options(
          headers: <String, Object?>{
            'authorization': 'Bearer $token',
            'content-type': 'application/json',
            'accept': 'application/json',
          },
          responseType: ResponseType.stream,
          receiveDataWhenStatusError: false,
          sendTimeout: const Duration(seconds: 8),
          receiveTimeout: const Duration(seconds: 8),
          followRedirects: false,
          maxRedirects: 0,
          validateStatus: (int? status) => status == 200,
        ),
      );

      final body = response.data;
      if (body == null || !_hasSingleJsonContentType(response.headers)) {
        return _denied('mutation_authority_response_invalid');
      }
      final declaredLength = _declaredContentLength(response.headers);
      if (declaredLength != null &&
          declaredLength > HttpMutationAuthorityProvider.maxResponseBytes) {
        return _denied('mutation_authority_response_invalid');
      }
      final bodyBytes = await _readBounded(body.stream);
      if (declaredLength != null && declaredLength != bodyBytes.length) {
        return _denied('mutation_authority_response_invalid');
      }
      return decodeAuthorizationBytes(
        bodyBytes,
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
    } on Object {
      // Token providers, clocks, adapters and response streams are external
      // dependencies. Unexpected failures must deny rather than escape the
      // authority boundary or mint a lease from partial state.
      return _denied('mutation_authority_unavailable');
    }
  }

  static Future<Uint8List> _readBounded(
    Stream<Uint8List> stream,
  ) async {
    final builder = BytesBuilder(copy: false);
    var length = 0;
    await for (final chunk in stream) {
      length += chunk.length;
      if (length > maxResponseBytes) {
        throw const FormatException(
          'mutation_authority_response_too_large',
        );
      }
      builder.add(chunk);
    }
    final bytes = builder.takeBytes();
    if (bytes.isEmpty) {
      throw const FormatException(
        'mutation_authority_response_empty',
      );
    }
    return bytes;
  }

  static bool _hasSingleJsonContentType(Headers headers) {
    final values = headers[Headers.contentTypeHeader];
    if (values == null || values.length != 1) {
      return false;
    }
    final parts = values.single.split(';');
    if (parts.isEmpty ||
        parts.first.trim().toLowerCase() != 'application/json') {
      return false;
    }
    var sawCharset = false;
    for (final rawParameter in parts.skip(1)) {
      final parameter = rawParameter.trim();
      final equals = parameter.indexOf('=');
      if (equals <= 0 || equals != parameter.lastIndexOf('=')) {
        return false;
      }
      final name = parameter.substring(0, equals).trim().toLowerCase();
      var value = parameter.substring(equals + 1).trim().toLowerCase();
      if (value.length >= 2 && value.startsWith('"') && value.endsWith('"')) {
        value = value.substring(1, value.length - 1);
      }
      if (name != 'charset' || sawCharset || value != 'utf-8') {
        return false;
      }
      sawCharset = true;
    }
    return true;
  }

  static int? _declaredContentLength(Headers headers) {
    final values = headers[Headers.contentLengthHeader];
    if (values == null) {
      return null;
    }
    if (values.length != 1 ||
        !RegExp(r'^(0|[1-9][0-9]*)$').hasMatch(values.single)) {
      throw const FormatException(
        'mutation_authority_content_length_invalid',
      );
    }
    final value = int.tryParse(values.single);
    if (value == null) {
      throw const FormatException(
        'mutation_authority_content_length_invalid',
      );
    }
    return value;
  }

  static MutationAuthorization decodeAuthorizationBytes(
    List<int> bodyBytes, {
    required MutationAuthorizationRequest request,
    required String expectedArgumentDigest,
    required DateTime now,
  }) {
    final value = decodeStrictJsonBytes(
      bodyBytes,
      maxBytes: maxResponseBytes,
    );
    if (value is! Map<String, Object?>) {
      throw const FormatException(
        'mutation_authority_response_shape_invalid',
      );
    }
    return decodeAuthorization(
      Map<Object?, Object?>.from(value),
      request: request,
      expectedArgumentDigest: expectedArgumentDigest,
      now: now,
    );
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
        body.length != fields.length ||
        !body.keys.cast<String>().every(fields.contains)) {
      throw const FormatException(
        'mutation_authority_response_shape_invalid',
      );
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
      throw const FormatException(
        'mutation_authority_response_binding_invalid',
      );
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
    if (issuedAt.isAfter(
          normalizedNow.add(const Duration(seconds: 30)),
        ) ||
        !expiresAt.isAfter(normalizedNow) ||
        expiresAt.isAfter(request.deadline) ||
        !expiresAt.isAfter(issuedAt) ||
        (request.riskTier == RiskTier.r2 && !userPresent) ||
        (request.riskTier == RiskTier.r3 &&
            (!userPresent || !biometricVerified)) ||
        request.riskTier == RiskTier.r4) {
      throw const FormatException(
        'mutation_authority_response_time_invalid',
      );
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
      value.codeUnits.every(
        (int unit) => unit >= 33 && unit <= 126,
      );

  static Uri _validatedUri(
    Uri uri,
    bool allowInsecureLoopback,
  ) {
    final loopback = <String>{
      '127.0.0.1',
      'localhost',
      '::1',
    }.contains(uri.host);
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

  static final RegExp _identifier = RegExp(
    r'^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$',
  );
  static final RegExp _digest = RegExp(r'^[a-f0-9]{64}$');
}
