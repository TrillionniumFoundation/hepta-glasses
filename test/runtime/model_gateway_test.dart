import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hepta_glasses/runtime/model_gateway.dart';

final class _RecordingDio {
  _RecordingDio({
    String body = '{"answer":"ok"}',
    List<List<int>>? chunks,
    int statusCode = 200,
    String contentType = 'application/json; charset=utf-8',
    int? declaredLength,
    bool includeLength = true,
    this.chunkDelay = Duration.zero,
    this.neverComplete = false,
  })  : responseChunks = chunks ?? <List<int>>[utf8.encode(body)],
        responseStatusCode = statusCode,
        responseContentType = contentType,
        declaredLength = declaredLength,
        includeLength = includeLength {
    dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (
          RequestOptions options,
          RequestInterceptorHandler handler,
        ) {
          requests++;
          lastOptions = options;
          streamCancelled = false;
          late final StreamController<Uint8List> controller;
          controller = StreamController<Uint8List>(
            onListen: () {
              streamListeners++;
              unawaited(_emit(controller));
            },
            onCancel: () {
              streamCancelled = true;
              streamCancellations++;
            },
          );
          final headers = <String, List<String>>{
            Headers.contentTypeHeader: <String>[responseContentType],
            if (includeLength)
              Headers.contentLengthHeader: <String>[
                (declaredLength ?? totalResponseBytes).toString(),
              ],
          };
          handler.resolve(
            Response<ResponseBody>(
              requestOptions: options,
              statusCode: responseStatusCode,
              data: ResponseBody(
                controller.stream,
                responseStatusCode,
                headers: headers,
              ),
              headers: Headers.fromMap(headers),
            ),
          );
        },
      ),
    );
  }

  final Dio dio = Dio();
  final List<List<int>> responseChunks;
  final int responseStatusCode;
  final String responseContentType;
  final int? declaredLength;
  final bool includeLength;
  final Duration chunkDelay;
  final bool neverComplete;
  int requests = 0;
  int streamListeners = 0;
  int streamCancellations = 0;
  int chunksEmitted = 0;
  bool streamCancelled = false;
  RequestOptions? lastOptions;

  int get totalResponseBytes =>
      responseChunks.fold<int>(0, (int total, List<int> value) {
        return total + value.length;
      });

  Future<void> _emit(StreamController<Uint8List> controller) async {
    for (final chunk in responseChunks) {
      if (chunkDelay > Duration.zero) {
        await Future<void>.delayed(chunkDelay);
      }
      if (streamCancelled || controller.isClosed) {
        return;
      }
      controller.add(Uint8List.fromList(chunk));
      chunksEmitted++;
    }
    if (neverComplete || streamCancelled || controller.isClosed) {
      return;
    }
    await controller.close();
  }
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
  RuntimeTokenProvider tokenProvider, {
  Duration responseDeadline = const Duration(seconds: 2),
}) =>
    HttpModelGateway(
      baseUri: Uri.parse('https://gateway.example/'),
      tokenProvider: tokenProvider,
      dio: transport.dio,
      responseDeadline: responseDeadline,
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
      gateway.answer(question: 'status', cancellation: cancellation),
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
    await expectLater(
      _gateway(
        transport,
        const StaticRuntimeTokenProvider(null),
      ).answer(question: 'private question'),
      _gatewayCode('model_gateway_unauthenticated'),
    );
    expect(transport.requests, 0);
  });

  test('token provider failure performs zero network requests', () async {
    final transport = _RecordingDio();
    await expectLater(
      _gateway(transport, _ThrowingTokenProvider())
          .answer(question: 'private question'),
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
    await expectLater(
      _gateway(transport, provider).answer(question: 'private question'),
      _gatewayCode('model_gateway_authority_changed'),
    );
    expect(provider.reads, 2);
    expect(transport.requests, 0);
  });

  test('authenticated request uses a streamed closed wire profile', () async {
    final transport = _RecordingDio(body: '{"answer":" accepted "}');
    final gateway = _gateway(
      transport,
      const StaticRuntimeTokenProvider('stable-token-123456789'),
    );
    expect(
      await gateway.answer(question: ' status ', taskId: 'task-1'),
      'accepted',
    );
    expect(transport.requests, 1);
    expect(transport.streamListeners, 1);
    final options = transport.lastOptions!;
    expect(options.uri.toString(), 'https://gateway.example/v1/chat');
    expect(options.followRedirects, isFalse);
    expect(options.maxRedirects, 0);
    expect(options.responseType, ResponseType.stream);
    expect(options.headers['authorization'], 'Bearer stable-token-123456789');
    expect(options.headers['accept'], 'application/json');
  });

  test('chunked response without content length succeeds within bound',
      () async {
    final transport = _RecordingDio(
      chunks: <List<int>>[
        utf8.encode('{"ans'),
        utf8.encode('wer":"chunked"}'),
      ],
      includeLength: false,
    );
    expect(
      await _gateway(
        transport,
        const StaticRuntimeTokenProvider('stable-token-123456789'),
      ).answer(question: 'status'),
      'chunked',
    );
    expect(transport.streamListeners, 1);
  });

  test('oversized declared length is rejected before stream subscription',
      () async {
    final transport = _RecordingDio(
      declaredLength: HttpModelGateway.maxResponseBytes + 1,
    );
    await expectLater(
      _gateway(
        transport,
        const StaticRuntimeTokenProvider('stable-token-123456789'),
      ).answer(question: 'status'),
      _gatewayCode('model_gateway_response_size_invalid'),
    );
    expect(transport.streamListeners, 0);
  });

  test('lying small content length cancels at first excess byte', () async {
    final first = utf8.encode('{"answer":');
    final transport = _RecordingDio(
      chunks: <List<int>>[first, utf8.encode('"too-long"}')],
      declaredLength: first.length,
      chunkDelay: const Duration(milliseconds: 1),
    );
    await expectLater(
      _gateway(
        transport,
        const StaticRuntimeTokenProvider('stable-token-123456789'),
      ).answer(question: 'status'),
      _gatewayCode('model_gateway_response_size_invalid'),
    );
    expect(transport.streamCancellations, greaterThanOrEqualTo(1));
  });

  test('chunked oversized response is cancelled before full materialization',
      () async {
    final chunks = List<List<int>>.generate(
      70,
      (int _) => List<int>.filled(1024, 0x78),
    );
    final transport = _RecordingDio(
      chunks: chunks,
      includeLength: false,
      chunkDelay: const Duration(milliseconds: 1),
    );
    await expectLater(
      _gateway(
        transport,
        const StaticRuntimeTokenProvider('stable-token-123456789'),
      ).answer(question: 'status'),
      _gatewayCode('model_gateway_response_size_invalid'),
    );
    expect(transport.chunksEmitted, lessThan(chunks.length));
    expect(transport.streamCancellations, greaterThanOrEqualTo(1));
  });

  test('slow response is cancelled by one total deadline', () async {
    final transport = _RecordingDio(
      chunkDelay: const Duration(milliseconds: 100),
    );
    await expectLater(
      _gateway(
        transport,
        const StaticRuntimeTokenProvider('stable-token-123456789'),
        responseDeadline: const Duration(milliseconds: 20),
      ).answer(question: 'status'),
      _gatewayCode('model_gateway_response_timeout'),
    );
    expect(transport.streamCancellations, greaterThanOrEqualTo(1));
  });

  test('complete JSON on an unterminated stream still times out', () async {
    final transport = _RecordingDio(
      includeLength: false,
      neverComplete: true,
    );
    await expectLater(
      _gateway(
        transport,
        const StaticRuntimeTokenProvider('stable-token-123456789'),
        responseDeadline: const Duration(milliseconds: 50),
      ).answer(question: 'status'),
      _gatewayCode('model_gateway_response_timeout'),
    );
    expect(transport.requests, 1);
    expect(transport.streamListeners, 1);
    expect(transport.chunksEmitted, 1);
    expect(transport.streamCancellations, 1);
  });

  test('cancellation during response immediately cancels stream', () async {
    final transport = _RecordingDio(
      chunkDelay: const Duration(milliseconds: 100),
    );
    final cancellation = ModelRequestCancellation();
    final expectation = expectLater(
      _gateway(
        transport,
        const StaticRuntimeTokenProvider('stable-token-123456789'),
      ).answer(question: 'status', cancellation: cancellation),
      _gatewayCode('model_request_cancelled'),
    );
    await Future<void>.delayed(const Duration(milliseconds: 10));
    cancellation.cancel('session-revoked');
    await expectation;
    expect(transport.streamCancellations, greaterThanOrEqualTo(1));
  });

  test('authority change before answer publication fails closed', () async {
    final transport = _RecordingDio();
    final provider = _SequenceTokenProvider(<String?>[
      'stable-token-123456789',
      'stable-token-123456789',
      null,
    ]);
    await expectLater(
      _gateway(transport, provider).answer(question: 'private question'),
      _gatewayCode('model_gateway_authority_changed'),
    );
    expect(provider.reads, 3);
    expect(transport.requests, 1);
  });

  test('duplicate JSON response members fail closed', () async {
    final transport = _RecordingDio(
      body: '{"answer":"first","answer":"second"}',
    );
    await expectLater(
      _gateway(
        transport,
        const StaticRuntimeTokenProvider('stable-token-123456789'),
      ).answer(question: 'status'),
      _gatewayCode('model_gateway_response_json_invalid'),
    );
  });

  test('unknown response fields fail the closed shape', () async {
    final transport = _RecordingDio(
      body: '{"answer":"ok","provider":"untrusted"}',
    );
    await expectLater(
      _gateway(
        transport,
        const StaticRuntimeTokenProvider('stable-token-123456789'),
      ).answer(question: 'status'),
      _gatewayCode('model_gateway_response_shape_invalid'),
    );
  });

  test('content type and terminal length mismatch are enforced', () async {
    final wrongType = _RecordingDio(contentType: 'text/plain');
    await expectLater(
      _gateway(
        wrongType,
        const StaticRuntimeTokenProvider('stable-token-123456789'),
      ).answer(question: 'status'),
      _gatewayCode('model_gateway_response_content_type_invalid'),
    );
    final wrongLength = _RecordingDio(declaredLength: 999);
    await expectLater(
      _gateway(
        wrongLength,
        const StaticRuntimeTokenProvider('stable-token-123456789'),
      ).answer(question: 'status'),
      _gatewayCode('model_gateway_response_size_invalid'),
    );
  });

  test('redirect response cannot become an answer', () async {
    final transport = _RecordingDio(statusCode: 302);
    await expectLater(
      _gateway(
        transport,
        const StaticRuntimeTokenProvider('stable-token-123456789'),
      ).answer(question: 'status'),
      _gatewayCode('gateway_http_302'),
    );
    expect(transport.streamListeners, 0);
  });

  test('unsupported context fails before token and network use', () async {
    final transport = _RecordingDio();
    final provider = _SequenceTokenProvider(<String?>[
      'stable-token-123456789',
    ]);
    await expectLater(
      _gateway(transport, provider).answer(
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
