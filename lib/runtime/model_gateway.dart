import 'dart:convert';

import 'package:dio/dio.dart';

import 'strict_json.dart';

final class ModelRequestCancellation {
  final CancelToken _token = CancelToken();

  bool get isCancelled => _token.isCancelled;

  void cancel([String reason = 'cancelled']) {
    if (!_token.isCancelled) {
      _token.cancel(reason);
    }
  }
}

abstract interface class ModelGateway {
  Future<String> answer({
    required String question,
    String? taskId,
    Map<String, Object?> context = const <String, Object?>{},
    ModelRequestCancellation? cancellation,
  });
}

abstract interface class RuntimeTokenProvider {
  Future<String?> getToken();
}

final class StaticRuntimeTokenProvider implements RuntimeTokenProvider {
  const StaticRuntimeTokenProvider(this.token);

  final String? token;

  @override
  Future<String?> getToken() async => token;
}

final class ModelGatewayException implements Exception {
  const ModelGatewayException(this.code);

  final String code;

  @override
  String toString() => 'ModelGatewayException($code)';
}

final class UnavailableModelGateway implements ModelGateway {
  const UnavailableModelGateway([this.reason = 'model_gateway_not_configured']);

  final String reason;

  @override
  Future<String> answer({
    required String question,
    String? taskId,
    Map<String, Object?> context = const <String, Object?>{},
    ModelRequestCancellation? cancellation,
  }) async {
    throw ModelGatewayException(reason);
  }
}

final class DeterministicModelGateway implements ModelGateway {
  const DeterministicModelGateway({this.prefix = 'Hepta'});

  final String prefix;

  @override
  Future<String> answer({
    required String question,
    String? taskId,
    Map<String, Object?> context = const <String, Object?>{},
    ModelRequestCancellation? cancellation,
  }) async {
    if (cancellation?.isCancelled == true) {
      throw const ModelGatewayException('model_request_cancelled');
    }
    final trimmed = question.trim();
    if (trimmed.isEmpty) {
      throw const ModelGatewayException('empty_question');
    }
    return '$prefix: $trimmed';
  }
}

final class HttpModelGateway implements ModelGateway {
  HttpModelGateway({
    required Uri baseUri,
    required RuntimeTokenProvider tokenProvider,
    Dio? dio,
    bool allowInsecureLoopback = false,
  })  : _baseUri = _validatedGatewayUri(baseUri, allowInsecureLoopback),
        _tokenProvider = tokenProvider,
        _dio = dio ?? Dio();

  static const int maxRequestBytes = 64 * 1024;
  static const int maxResponseBytes = 64 * 1024;
  static const int maxQuestionCharacters = 8000;
  static const int maxContextBytes = 32 * 1024;
  static const int maxTaskIdCharacters = 128;
  static const int maxAnswerBytes = 64 * 1024;
  static const int maxJsonDepth = 8;
  static const int maxJsonNodes = 2048;
  static const int maxCollectionItems = 256;
  static const int maxStringCharacters = 8000;

  final Uri _baseUri;
  final RuntimeTokenProvider _tokenProvider;
  final Dio _dio;

  @override
  Future<String> answer({
    required String question,
    String? taskId,
    Map<String, Object?> context = const <String, Object?>{},
    ModelRequestCancellation? cancellation,
  }) async {
    if (cancellation?.isCancelled == true) {
      throw const ModelGatewayException('model_request_cancelled');
    }

    final normalizedQuestion = question.trim();
    final normalizedTaskId = taskId?.trim();
    if (normalizedQuestion.isEmpty ||
        normalizedQuestion.length > maxQuestionCharacters ||
        (normalizedTaskId != null &&
            (normalizedTaskId.isEmpty ||
                normalizedTaskId.length > maxTaskIdCharacters))) {
      throw const ModelGatewayException('model_request_invalid');
    }

    try {
      _validateJsonValue(context);
    } on Object {
      throw const ModelGatewayException('model_request_invalid');
    }
    final contextBytes = utf8.encode(jsonEncode(context));
    if (contextBytes.length > maxContextBytes) {
      throw const ModelGatewayException('model_request_too_large');
    }

    final requestDocument = <String, Object?>{
      'question': normalizedQuestion,
      'task_id': normalizedTaskId,
      'context': context,
    };
    final requestBytes = utf8.encode(jsonEncode(requestDocument));
    if (requestBytes.length > maxRequestBytes) {
      throw const ModelGatewayException('model_request_too_large');
    }

    final firstToken = await _readValidToken();
    if (cancellation?.isCancelled == true) {
      throw const ModelGatewayException('model_request_cancelled');
    }
    final secondToken = await _readValidToken();
    if (firstToken != secondToken) {
      throw const ModelGatewayException(
        'model_gateway_authority_changed',
      );
    }
    if (cancellation?.isCancelled == true) {
      throw const ModelGatewayException('model_request_cancelled');
    }

    try {
      final response = await _dio.postUri<List<int>>(
        _baseUri.resolve('v1/chat'),
        data: requestDocument,
        options: Options(
          headers: <String, Object?>{
            'authorization': 'Bearer $secondToken',
            'content-type': 'application/json',
            'accept': 'application/json',
          },
          responseType: ResponseType.bytes,
          sendTimeout: const Duration(seconds: 10),
          receiveTimeout: const Duration(seconds: 60),
          receiveDataWhenStatusError: false,
          followRedirects: false,
          maxRedirects: 0,
          validateStatus: (int? status) => status == 200,
        ),
        cancelToken: cancellation?._token,
      );
      if (cancellation?.isCancelled == true) {
        throw const ModelGatewayException('model_request_cancelled');
      }
      if (response.statusCode != 200) {
        throw ModelGatewayException(
          'gateway_http_${response.statusCode ?? 'unknown'}',
        );
      }
      if (!_hasSingleJsonContentType(response.headers)) {
        throw const ModelGatewayException(
          'model_gateway_response_content_type_invalid',
        );
      }
      final bytes = response.data;
      if (bytes == null || bytes.isEmpty || bytes.length > maxResponseBytes) {
        throw const ModelGatewayException(
          'model_gateway_response_size_invalid',
        );
      }
      final declaredLength = _declaredContentLength(response.headers);
      if (declaredLength != null && declaredLength != bytes.length) {
        throw const ModelGatewayException(
          'model_gateway_response_size_invalid',
        );
      }
      final value = decodeStrictJsonBytes(
        bytes,
        maxBytes: maxResponseBytes,
        maxDepth: maxJsonDepth,
        maxTokens: maxJsonNodes,
      );
      if (value is! Map<String, Object?> ||
          value.length != 1 ||
          !value.containsKey('answer')) {
        throw const ModelGatewayException(
          'model_gateway_response_shape_invalid',
        );
      }
      final answerValue = value['answer'];
      if (answerValue is! String) {
        throw const ModelGatewayException(
          'model_gateway_response_shape_invalid',
        );
      }
      final answer = answerValue.trim();
      if (answer.isEmpty || utf8.encode(answer).length > maxAnswerBytes) {
        throw const ModelGatewayException(
          'model_gateway_response_answer_invalid',
        );
      }
      return answer;
    } on ModelGatewayException {
      rethrow;
    } on DioException catch (error) {
      if (CancelToken.isCancel(error)) {
        throw const ModelGatewayException('model_request_cancelled');
      }
      final status = error.response?.statusCode;
      throw ModelGatewayException(
        status == null ? 'gateway_unreachable' : 'gateway_http_$status',
      );
    } on FormatException {
      throw const ModelGatewayException(
        'model_gateway_response_json_invalid',
      );
    } on Object {
      throw const ModelGatewayException('gateway_unreachable');
    }
  }

  Future<String> _readValidToken() async {
    try {
      final token = await _tokenProvider.getToken();
      if (!_validBearer(token)) {
        throw const ModelGatewayException(
          'model_gateway_unauthenticated',
        );
      }
      return token!;
    } on ModelGatewayException {
      rethrow;
    } on Object {
      throw const ModelGatewayException(
        'model_gateway_unauthenticated',
      );
    }
  }

  static bool _validBearer(String? value) =>
      value != null &&
      value.length >= 16 &&
      value.length <= 8192 &&
      value.codeUnits.every((int unit) => unit >= 33 && unit <= 126);

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
      throw const ModelGatewayException(
        'model_gateway_response_size_invalid',
      );
    }
    final value = int.tryParse(values.single);
    if (value == null || value > maxResponseBytes) {
      throw const ModelGatewayException(
        'model_gateway_response_size_invalid',
      );
    }
    return value;
  }

  static int _validateJsonValue(
    Object? value, {
    int depth = 0,
    int nodes = 0,
  }) {
    if (depth > maxJsonDepth || nodes >= maxJsonNodes) {
      throw const FormatException(
        'JSON value exceeds structural bounds.',
      );
    }
    final nextNodes = nodes + 1;
    if (value == null || value is bool || value is int) {
      return nextNodes;
    }
    if (value is double) {
      if (!value.isFinite) {
        throw const FormatException('JSON number must be finite.');
      }
      return nextNodes;
    }
    if (value is String) {
      if (value.length > maxStringCharacters) {
        throw const FormatException('JSON string exceeds the limit.');
      }
      return nextNodes;
    }
    if (value is List<Object?>) {
      if (value.length > maxCollectionItems) {
        throw const FormatException(
          'JSON array exceeds the item limit.',
        );
      }
      var count = nextNodes;
      for (final item in value) {
        count = _validateJsonValue(
          item,
          depth: depth + 1,
          nodes: count,
        );
      }
      return count;
    }
    if (value is Map<String, Object?>) {
      if (value.length > maxCollectionItems) {
        throw const FormatException(
          'JSON object exceeds the member limit.',
        );
      }
      var count = nextNodes;
      for (final entry in value.entries) {
        if (entry.key.isEmpty || entry.key.length > maxStringCharacters) {
          throw const FormatException('JSON object key is invalid.');
        }
        count = _validateJsonValue(
          entry.value,
          depth: depth + 1,
          nodes: count,
        );
      }
      return count;
    }
    throw const FormatException(
      'Value is not in the supported JSON domain.',
    );
  }
}

final class ModelGatewayRegistry {
  ModelGatewayRegistry._();

  static ModelGateway _current = const UnavailableModelGateway();

  static ModelGateway get current => _current;

  static void configure(ModelGateway gateway) {
    _current = gateway;
  }

  static void reset() {
    _current = const UnavailableModelGateway();
  }
}

final class ModelGatewayBootstrap {
  ModelGatewayBootstrap._();

  static void configureFromDevelopmentEnvironment() {
    const url = String.fromEnvironment('HEPTA_MODEL_GATEWAY_URL');
    const token = String.fromEnvironment('HEPTA_MODEL_GATEWAY_DEV_TOKEN');
    const product = bool.fromEnvironment('dart.vm.product');

    if (product && token.isNotEmpty) {
      ModelGatewayRegistry.configure(
        const UnavailableModelGateway('compiled_token_forbidden_in_product'),
      );
      return;
    }
    if (url.isEmpty) {
      ModelGatewayRegistry.configure(const UnavailableModelGateway());
      return;
    }
    final uri = Uri.tryParse(url);
    if (uri == null || !uri.hasScheme || uri.host.isEmpty) {
      ModelGatewayRegistry.configure(
        const UnavailableModelGateway('invalid_gateway_url'),
      );
      return;
    }
    try {
      ModelGatewayRegistry.configure(
        HttpModelGateway(
          baseUri: uri,
          tokenProvider: StaticRuntimeTokenProvider(
            token.isEmpty ? null : token,
          ),
          allowInsecureLoopback: !product,
        ),
      );
    } on ArgumentError {
      ModelGatewayRegistry.configure(
        const UnavailableModelGateway('insecure_gateway_url'),
      );
    }
  }
}

final class SpeechBootstrapException implements Exception {
  const SpeechBootstrapException(this.code);

  final String code;

  @override
  String toString() => 'SpeechBootstrapException($code)';
}

final class SpeechBootstrap {
  const SpeechBootstrap({
    required this.bootstrapId,
    required this.sessionId,
    required this.generation,
    required this.pairIdentity,
    required this.locale,
    required this.endpoint,
    required this.bearerToken,
    required this.provider,
    required this.expiresAtEpochSeconds,
    required this.maximumAudioBytes,
  });

  final String bootstrapId;
  final String sessionId;
  final int generation;
  final String pairIdentity;
  final String locale;
  final Uri endpoint;
  final String bearerToken;
  final String provider;
  final int expiresAtEpochSeconds;
  final int maximumAudioBytes;

  factory SpeechBootstrap.fromMap(
    Map<Object?, Object?> value, {
    required String expectedSessionId,
    required int expectedGeneration,
    required String expectedPairIdentity,
    required String expectedLocale,
    int? nowEpochSeconds,
  }) {
    const requiredKeys = <String>{
      'bootstrap_id',
      'session_id',
      'generation',
      'pair_identity',
      'locale',
      'endpoint',
      'bearer_token',
      'provider',
      'expires_at',
      'maximum_audio_bytes',
    };
    if (value.keys.any((Object? key) => key is! String) ||
        value.keys.cast<String>().toSet().difference(requiredKeys).isNotEmpty ||
        requiredKeys.difference(value.keys.cast<String>().toSet()).isNotEmpty) {
      throw const SpeechBootstrapException(
        'speech_bootstrap_response_shape_invalid',
      );
    }

    final bootstrapId = value['bootstrap_id'];
    final sessionId = value['session_id'];
    final generation = value['generation'];
    final pairIdentity = value['pair_identity'];
    final locale = value['locale'];
    final endpointValue = value['endpoint'];
    final bearerToken = value['bearer_token'];
    final provider = value['provider'];
    final expiresAt = value['expires_at'];
    final maximumAudioBytes = value['maximum_audio_bytes'];

    if (bootstrapId is! String ||
        bootstrapId.isEmpty ||
        bootstrapId.length > 512 ||
        sessionId != expectedSessionId ||
        generation != expectedGeneration ||
        pairIdentity != expectedPairIdentity ||
        locale != expectedLocale ||
        endpointValue is! String ||
        bearerToken is! String ||
        bearerToken.length < 16 ||
        bearerToken.length > 8192 ||
        bearerToken.codeUnits.any((int unit) => unit <= 32 || unit == 127) ||
        provider is! String ||
        provider.isEmpty ||
        provider.length > 128 ||
        expiresAt is! int ||
        maximumAudioBytes is! int ||
        maximumAudioBytes < 3200 ||
        maximumAudioBytes > 1920000) {
      throw const SpeechBootstrapException(
        'speech_bootstrap_response_binding_invalid',
      );
    }

    final endpoint = Uri.tryParse(endpointValue);
    if (endpoint == null ||
        endpoint.scheme != 'https' ||
        endpoint.host.isEmpty ||
        endpoint.userInfo.isNotEmpty ||
        endpoint.fragment.isNotEmpty ||
        (endpoint.hasPort && endpoint.port != 443)) {
      throw const SpeechBootstrapException(
        'speech_bootstrap_endpoint_invalid',
      );
    }

    final now = nowEpochSeconds ??
        DateTime.now().toUtc().millisecondsSinceEpoch ~/ 1000;
    if (expiresAt <= now || expiresAt - now > 300) {
      throw const SpeechBootstrapException('speech_bootstrap_expired');
    }

    return SpeechBootstrap(
      bootstrapId: bootstrapId,
      sessionId: sessionId as String,
      generation: generation as int,
      pairIdentity: pairIdentity as String,
      locale: locale as String,
      endpoint: endpoint,
      bearerToken: bearerToken,
      provider: provider,
      expiresAtEpochSeconds: expiresAt,
      maximumAudioBytes: maximumAudioBytes,
    );
  }

  Map<String, Object?> toNativeArguments() => <String, Object?>{
        'sessionId': sessionId,
        'generation': generation,
        'pairIdentity': pairIdentity,
        'locale': locale,
        'endpoint': endpoint.toString(),
        'bearerToken': bearerToken,
        'expiresAtEpochSeconds': expiresAtEpochSeconds,
        'maximumAudioBytes': maximumAudioBytes,
      };
}

abstract interface class SpeechBootstrapGateway {
  Future<SpeechBootstrap> issue({
    required String sessionId,
    required int generation,
    required String pairIdentity,
    required String locale,
    ModelRequestCancellation? cancellation,
  });
}

final class UnavailableSpeechBootstrapGateway
    implements SpeechBootstrapGateway {
  const UnavailableSpeechBootstrapGateway([
    this.reason = 'speech_bootstrap_not_configured',
  ]);

  final String reason;

  @override
  Future<SpeechBootstrap> issue({
    required String sessionId,
    required int generation,
    required String pairIdentity,
    required String locale,
    ModelRequestCancellation? cancellation,
  }) async {
    throw SpeechBootstrapException(reason);
  }
}

final class HttpSpeechBootstrapGateway implements SpeechBootstrapGateway {
  HttpSpeechBootstrapGateway({
    required Uri baseUri,
    required RuntimeTokenProvider tokenProvider,
    Dio? dio,
    bool allowInsecureLoopback = false,
  })  : _baseUri = _validatedGatewayUri(baseUri, allowInsecureLoopback),
        _tokenProvider = tokenProvider,
        _dio = dio ?? Dio();

  final Uri _baseUri;
  final RuntimeTokenProvider _tokenProvider;
  final Dio _dio;

  @override
  Future<SpeechBootstrap> issue({
    required String sessionId,
    required int generation,
    required String pairIdentity,
    required String locale,
    ModelRequestCancellation? cancellation,
  }) async {
    final normalizedSession = sessionId.trim();
    final normalizedPair = pairIdentity.trim();
    final normalizedLocale = locale.trim();
    if (normalizedSession.isEmpty ||
        normalizedSession.length > 128 ||
        generation <= 0 ||
        normalizedPair.isEmpty ||
        normalizedPair.length > 128 ||
        !RegExp(r'^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})?$')
            .hasMatch(normalizedLocale)) {
      throw const SpeechBootstrapException(
        'speech_bootstrap_request_invalid',
      );
    }
    if (cancellation?.isCancelled == true) {
      throw const SpeechBootstrapException('speech_bootstrap_cancelled');
    }
    final token = await _tokenProvider.getToken();
    if (cancellation?.isCancelled == true) {
      throw const SpeechBootstrapException('speech_bootstrap_cancelled');
    }
    if (token == null || token.length < 16) {
      throw const SpeechBootstrapException(
        'speech_bootstrap_unauthenticated',
      );
    }

    try {
      final response = await _dio.postUri<Object?>(
        _baseUri.resolve('v1/speech/bootstrap'),
        data: <String, Object?>{
          'session_id': normalizedSession,
          'generation': generation,
          'pair_identity': normalizedPair,
          'locale': normalizedLocale,
        },
        options: Options(
          headers: <String, Object?>{
            'content-type': 'application/json',
            'authorization': 'Bearer $token',
          },
          sendTimeout: const Duration(seconds: 8),
          receiveTimeout: const Duration(seconds: 8),
        ),
        cancelToken: cancellation?._token,
      );
      final data = response.data;
      if (data is! Map) {
        throw const SpeechBootstrapException(
          'speech_bootstrap_response_shape_invalid',
        );
      }
      return SpeechBootstrap.fromMap(
        data.cast<Object?, Object?>(),
        expectedSessionId: normalizedSession,
        expectedGeneration: generation,
        expectedPairIdentity: normalizedPair,
        expectedLocale: normalizedLocale,
      );
    } on SpeechBootstrapException {
      rethrow;
    } on DioException catch (error) {
      if (CancelToken.isCancel(error)) {
        throw const SpeechBootstrapException('speech_bootstrap_cancelled');
      }
      final status = error.response?.statusCode;
      throw SpeechBootstrapException(
        status == null
            ? 'speech_bootstrap_unreachable'
            : 'speech_bootstrap_http_$status',
      );
    }
  }
}

final class SpeechBootstrapGatewayRegistry {
  SpeechBootstrapGatewayRegistry._();

  static SpeechBootstrapGateway _current =
      const UnavailableSpeechBootstrapGateway();

  static SpeechBootstrapGateway get current => _current;

  static void configure(SpeechBootstrapGateway gateway) {
    _current = gateway;
  }

  static void reset() {
    _current = const UnavailableSpeechBootstrapGateway();
  }
}

final class SpeechBootstrapBootstrap {
  SpeechBootstrapBootstrap._();

  static void configureFromDevelopmentEnvironment() {
    const url = String.fromEnvironment('HEPTA_SPEECH_BOOTSTRAP_URL');
    const token = String.fromEnvironment('HEPTA_SPEECH_BOOTSTRAP_DEV_TOKEN');
    const product = bool.fromEnvironment('dart.vm.product');

    if (product && token.isNotEmpty) {
      SpeechBootstrapGatewayRegistry.configure(
        const UnavailableSpeechBootstrapGateway(
          'compiled_speech_token_forbidden_in_product',
        ),
      );
      return;
    }
    if (url.isEmpty) {
      SpeechBootstrapGatewayRegistry.configure(
        const UnavailableSpeechBootstrapGateway(),
      );
      return;
    }
    final uri = Uri.tryParse(url);
    if (uri == null || !uri.hasScheme || uri.host.isEmpty) {
      SpeechBootstrapGatewayRegistry.configure(
        const UnavailableSpeechBootstrapGateway(
          'invalid_speech_bootstrap_url',
        ),
      );
      return;
    }
    try {
      SpeechBootstrapGatewayRegistry.configure(
        HttpSpeechBootstrapGateway(
          baseUri: uri,
          tokenProvider: StaticRuntimeTokenProvider(
            token.isEmpty ? null : token,
          ),
          allowInsecureLoopback: !product,
        ),
      );
    } on ArgumentError {
      SpeechBootstrapGatewayRegistry.configure(
        const UnavailableSpeechBootstrapGateway(
          'insecure_speech_bootstrap_url',
        ),
      );
    }
  }
}

Uri _validatedGatewayUri(Uri uri, bool allowInsecureLoopback) {
  final loopback = <String>{
    '127.0.0.1',
    'localhost',
    '::1',
  }.contains(uri.host);
  if (uri.userInfo.isNotEmpty || uri.fragment.isNotEmpty) {
    throw ArgumentError.value(
      uri,
      'baseUri',
      'must not contain credentials or a fragment',
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
    'must use HTTPS, except explicit development loopback',
  );
}
