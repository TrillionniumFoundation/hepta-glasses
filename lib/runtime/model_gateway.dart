import 'package:dio/dio.dart';

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
  }) : _baseUri = _validatedUri(baseUri, allowInsecureLoopback),
       _tokenProvider = tokenProvider,
       _dio = dio ?? Dio();

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
    final trimmed = question.trim();
    if (trimmed.isEmpty) {
      throw const ModelGatewayException('empty_question');
    }
    final token = await _tokenProvider.getToken();
    if (cancellation?.isCancelled == true) {
      throw const ModelGatewayException('model_request_cancelled');
    }
    final headers = <String, Object?>{
      'content-type': 'application/json',
      if (token != null && token.isNotEmpty) 'authorization': 'Bearer $token',
    };
    try {
      final response = await _dio.postUri<Object?>(
        _baseUri.resolve('v1/chat'),
        data: <String, Object?>{
          'question': trimmed,
          'task_id': taskId,
          'context': context,
        },
        options: Options(
          headers: headers,
          sendTimeout: const Duration(seconds: 10),
          receiveTimeout: const Duration(seconds: 60),
        ),
        cancelToken: cancellation?._token,
      );
      final data = response.data;
      if (data is Map && data['answer'] is String) {
        final answer = (data['answer']! as String).trim();
        if (answer.isNotEmpty) {
          return answer;
        }
      }
      throw const ModelGatewayException('invalid_gateway_response');
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
    }
  }

  static Uri _validatedUri(Uri uri, bool allowInsecureLoopback) {
    final loopback = <String>{
      '127.0.0.1',
      'localhost',
      '::1',
    }.contains(uri.host);
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
