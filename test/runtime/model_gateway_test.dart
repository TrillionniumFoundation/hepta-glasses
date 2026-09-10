import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hepta_glasses/runtime/model_gateway.dart';

final class _RecordingDio {
  _RecordingDio({
    String body = '{"answer":"ok"}',
    int statusCode = 200,
    String contentType = 'application/json; charset=utf-8',
    int? declaredLength,
  })  : responseBytes = utf8.encode(body),
        statusCode = statusCode,
        contentType = contentType,
        declaredLength = declaredLength {
    dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (
          RequestOptions options,
          RequestInterceptorHandler handler,
        ) {
          requests++;
          lastOptions = options;
          handler.resolve(
            Response<List<int>>(
              requestOptions: options,
              statusCode: this.statusCode,
              data: responseBytes,
              headers: Headers.fromMap(<String, List<String>>{
                Headers.contentTypeHeader: <String>[this.contentType],
                Headers.contentLengthHeader: <String>[
                  (this.declaredLength ?? responseBytes.length).toString(),
                ],
              }),
            ),
          );
        },
      ),
    );
  }

  final Dio dio = Dio();
  final List<int> responseBytes;
  final int statusCode;
  final String contentType;
  final int? declaredLength;
  int requests = 0;
  RequestOptions? lastOptions;
}

final class _SequenceTokenProvider implements RuntimeTokenProvider {
  _SequenceTokenProvider(this.values);

  final List<String?> values;
  int reads = 0;

  @override
  Future<String?> getToken() async {
    final index = reads < values.length ? reads : values.length - 1;
    reads++;
    return values[index];
  }
}

final class _ThrowingTokenProvider implements RuntimeTokenProvider {
  @override
  Future<String?> getToken() async {
    throw StateError('token source unavailable');
  }
}

Matcher _gatewayCode(String code) => throwsA(
      isA<ModelGatewayException>().having(
        (ModelGatewayException error) => error.code,
        'code',
        code,
      ),
    );

HttpModelGateway _gateway(
  _RecordingDio transport,
  RuntimeTokenProvider tokenProvider,
) =>
    HttpModelGateway(
      baseUri: Uri.parse('https://gateway.example/'),
      tokenProvider: tokenProvider,
      dio: transport.dio,
    );

void main() {
  test('deterministic gateway returns a bounded answer', () async {
    const gateway = DeterministicModelGateway(prefix: 'test');
    expect(await gateway.answer(question: 'status'), 'test: status');
  });

  test('model request observes cancellation before execution', () async {
    const gateway = DeterministicModelGateway(prefix: 'test');
    final cancellation = ModelRequestCancellation()..cancel('session-ended');
    await expectLater(
      gateway.answer(
        question: 'status',
        cancellation: cancellation,
      ),
      _gatewayCode('model_request_cancelled'),
    );
  });

  test('unconfigured gateway fails with a typed error', () async {
    const gateway = UnavailableModelGateway();
    await expectLater(
      gateway.answer(question: 'status'),
      throwsA(isA<ModelGatewayException>()),
    );
  });

  test('HTTP gateway rejects insecure non-loopback origins', () {
    expect(
      () => HttpModelGateway(
        baseUri: Uri.parse('http://example.invalid/'),
        tokenProvider: const StaticRuntimeTokenProvider(null),
        allowInsecureLoopback: true,
      ),
      throwsArgumentError,
    );
  });

  test('missing token performs zero network requests', () async {
    final transport = _RecordingDio();
    final gateway = _gateway(
      transport,
      const StaticRuntimeTokenProvider(null),
    );
    await expectLater(
      gateway.answer(question: 'private question'),
      _gatewayCode('model_gateway_unauthenticated'),
    );
    expect(transport.requests, 0);
  });

  test('token provider failure performs zero network requests', () async {
    final transport = _RecordingDio();
    final gateway = _gateway(transport, _ThrowingTokenProvider());
    await expectLater(
      gateway.answer(question: 'private question'),
      _gatewayCode('model_gateway_unauthenticated'),
    );
    expect(transport.requests, 0);
  });

  test('token rotation before send fails closed', () async {
    final transport = _RecordingDio();
    final provider = _SequenceTokenProvider(<String?>[
      'first-token-123456789',
      'second-token-123456789',
    ]);
    final gateway = _gateway(transport, provider);
    await expectLater(
      gateway.answer(question: 'private question'),
      _gatewayCode('model_gateway_authority_changed'),
    );
    expect(provider.reads, 2);
    expect(transport.requests, 0);
  });

  test('authenticated request uses a closed wire profile', () async {
    final transport = _RecordingDio(
      body: '{"answer":" accepted "}',
    );
    final gateway = _gateway(
      transport,
      const StaticRuntimeTokenProvider('stable-token-123456789'),
    );
    expect(
      await gateway.answer(question: ' status ', taskId: 'task-1'),
      'accepted',
    );
    expect(transport.requests, 1);
    final options = transport.lastOptions!;
    expect(options.uri.toString(), 'https://gateway.example/v1/chat');
    expect(options.followRedirects, isFalse);
    expect(options.maxRedirects, 0);
    expect(options.responseType, ResponseType.bytes);
    expect(
      options.headers['authorization'],
      'Bearer stable-token-123456789',
    );
    expect(options.headers['accept'], 'application/json');
  });

  test('duplicate JSON response members fail closed', () async {
    final transport = _RecordingDio(
      body: '{"answer":"first","answer":"second"}',
    );
    final gateway = _gateway(
      transport,
      const StaticRuntimeTokenProvider('stable-token-123456789'),
    );
    await expectLater(
      gateway.answer(question: 'status'),
      _gatewayCode('model_gateway_response_json_invalid'),
    );
  });

  test('unknown response fields fail the closed shape', () async {
    final transport = _RecordingDio(
      body: '{"answer":"ok","provider":"untrusted"}',
    );
    final gateway = _gateway(
      transport,
      const StaticRuntimeTokenProvider('stable-token-123456789'),
    );
    await expectLater(
      gateway.answer(question: 'status'),
      _gatewayCode('model_gateway_response_shape_invalid'),
    );
  });

  test('content type and length are enforced', () async {
    final wrongType = _RecordingDio(contentType: 'text/plain');
    await expectLater(
      _gateway(
        wrongType,
        const StaticRuntimeTokenProvider(
          'stable-token-123456789',
        ),
      ).answer(question: 'status'),
      _gatewayCode('model_gateway_response_content_type_invalid'),
    );
    final wrongLength = _RecordingDio(declaredLength: 999);
    await expectLater(
      _gateway(
        wrongLength,
        const StaticRuntimeTokenProvider(
          'stable-token-123456789',
        ),
      ).answer(question: 'status'),
      _gatewayCode('model_gateway_response_size_invalid'),
    );
  });

  test('oversized response is rejected', () async {
    final transport = _RecordingDio(
      body: jsonEncode(<String, String>{
        'answer': List<String>.filled(64 * 1024, 'x').join(),
      }),
    );
    final gateway = _gateway(
      transport,
      const StaticRuntimeTokenProvider('stable-token-123456789'),
    );
    await expectLater(
      gateway.answer(question: 'status'),
      _gatewayCode('model_gateway_response_size_invalid'),
    );
  });

  test('redirect response cannot become an answer', () async {
    final transport = _RecordingDio(statusCode: 302);
    final gateway = _gateway(
      transport,
      const StaticRuntimeTokenProvider('stable-token-123456789'),
    );
    await expectLater(
      gateway.answer(question: 'status'),
      _gatewayCode('gateway_http_302'),
    );
  });

  test('unsupported context fails before token and network use', () async {
    final transport = _RecordingDio();
    final provider = _SequenceTokenProvider(<String?>[
      'stable-token-123456789',
    ]);
    final gateway = _gateway(transport, provider);
    await expectLater(
      gateway.answer(
        question: 'status',
        context: <String, Object?>{'when': DateTime.utc(2026)},
      ),
      _gatewayCode('model_request_invalid'),
    );
    expect(provider.reads, 0);
    expect(transport.requests, 0);
  });

  test('speech bootstrap remains authority bound', () {
    final bootstrap = SpeechBootstrap.fromMap(
      <String, Object?>{
        'bootstrap_id': 'bootstrap-1',
        'session_id': 'session-1',
        'generation': 9,
        'pair_identity': 'Pair_7',
        'locale': 'en-US',
        'endpoint': 'https://speech.example/v1/asr',
        'bearer_token': 'ephemeral-token-123456789',
        'provider': 'speech-provider',
        'expires_at': 200,
        'maximum_audio_bytes': 6400,
      },
      expectedSessionId: 'session-1',
      expectedGeneration: 9,
      expectedPairIdentity: 'Pair_7',
      expectedLocale: 'en-US',
      nowEpochSeconds: 100,
    );
    expect(bootstrap.endpoint.scheme, 'https');
    expect(bootstrap.generation, 9);
  });
}
