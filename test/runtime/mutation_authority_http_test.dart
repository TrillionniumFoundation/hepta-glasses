import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:hepta_glasses/runtime/canonical_json.dart';
import 'package:hepta_glasses/runtime/contracts.dart';
import 'package:hepta_glasses/runtime/mutation_authority.dart';
import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';

final class _StubAdapter implements HttpClientAdapter {
  _StubAdapter(this.responseFactory);

  final ResponseBody Function(RequestOptions options) responseFactory;
  RequestOptions? lastOptions;

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    lastOptions = options;
    return responseFactory(options);
  }

  @override
  void close({bool force = false}) {}
}

final class _ThrowingTokenProvider implements MutationAccessTokenProvider {
  const _ThrowingTokenProvider();

  @override
  Future<String?> getToken() async {
    throw StateError('token store unavailable');
  }
}

void main() {
  final now = DateTime.utc(2026, 9, 9, 0, 30);
  const token = 'test-authority-token-0123456789';

  MutationAuthorizationRequest request() => MutationAuthorizationRequest(
        taskId: 'task-wire-1',
        action: 'device.display_text',
        arguments: const <String, Object?>{'text': 'hello'},
        riskTier: RiskTier.r3,
        deadline: now.add(const Duration(minutes: 5)),
      );

  Map<String, Object?> validBody() => <String, Object?>{
        'task_id': 'task-wire-1',
        'action': 'device.display_text',
        'risk_tier': 'r3',
        'argument_digest': sha256CanonicalJson(
          const <String, Object?>{'text': 'hello'},
        ),
        'subject': 'subject-1',
        'device_id': 'device-1',
        'policy_hash': List<String>.filled(64, 'a').join(),
        'authenticated': true,
        'user_present': true,
        'biometric_verified': true,
        'lease_id': 'lease-1',
        'allowed_actions': <String>['device.display_text'],
        'issued_at_epoch_seconds':
            now.millisecondsSinceEpoch ~/ Duration.millisecondsPerSecond,
        'expires_at_epoch_seconds':
            now.add(const Duration(minutes: 1)).millisecondsSinceEpoch ~/
                Duration.millisecondsPerSecond,
        'single_use': true,
      };

  String duplicateMemberJson(String name) {
    final body = validBody();
    final entries = body.entries
        .map(
          (entry) => '${jsonEncode(entry.key)}:${jsonEncode(entry.value)}',
        )
        .toList();
    entries.add('${jsonEncode(name)}:${jsonEncode(body[name])}');
    return '{${entries.join(',')}}';
  }

  ResponseBody responseBody(
    List<int> bytes, {
    int statusCode = 200,
    Map<String, List<String>>? headers,
    List<Uint8List>? chunks,
  }) {
    final responseChunks = chunks ?? <Uint8List>[Uint8List.fromList(bytes)];
    return ResponseBody(
      Stream<Uint8List>.fromIterable(responseChunks),
      statusCode,
      headers: headers ??
          <String, List<String>>{
            Headers.contentTypeHeader: <String>['application/json'],
            Headers.contentLengthHeader: <String>['${bytes.length}'],
          },
    );
  }

  Future<({MutationAuthorization result, _StubAdapter adapter})> authorize(
    List<int> bytes, {
    int statusCode = 200,
    Map<String, List<String>>? headers,
    List<Uint8List>? chunks,
  }) async {
    final adapter = _StubAdapter(
      (_) => responseBody(
        bytes,
        statusCode: statusCode,
        headers: headers,
        chunks: chunks,
      ),
    );
    final dio = Dio()..httpClientAdapter = adapter;
    final provider = HttpMutationAuthorityProvider(
      baseUri: Uri.parse('https://authority.example/api/'),
      tokenProvider: const StaticMutationAccessTokenProvider(token),
      dio: dio,
      clock: () => now,
    );
    final result = await provider.authorize(request());
    return (result: result, adapter: adapter);
  }

  void expectDenied(
    MutationAuthorization authorization, {
    String source = 'mutation_authority_response_invalid',
  }) {
    expect(authorization.source, source);
    expect(authorization.deviceId, 'unbound-device');
    expect(authorization.context.authenticated, isFalse);
    expect(authorization.context.userPresent, isFalse);
    expect(authorization.context.biometricVerified, isFalse);
    expect(authorization.lease, isNull);
  }

  test('actual authorize path consumes a raw response stream', () async {
    final bytes = utf8.encode(jsonEncode(validBody()));
    final outcome = await authorize(bytes);
    final authorization = outcome.result;
    final options = outcome.adapter.lastOptions;

    expect(authorization.source, 'identity_https');
    expect(authorization.deviceId, 'device-1');
    expect(authorization.context.authenticated, isTrue);
    expect(authorization.context.userPresent, isTrue);
    expect(authorization.context.biometricVerified, isTrue);
    expect(authorization.lease, isNotNull);
    expect(authorization.lease!.leaseId, 'lease-1');

    expect(options, isNotNull);
    expect(options!.method, 'POST');
    expect(
      options.uri,
      Uri.parse('https://authority.example/api/v1/mutation/authorize'),
    );
    expect(options.responseType, ResponseType.stream);
    expect(options.followRedirects, isFalse);
    expect(options.maxRedirects, 0);
    expect(options.receiveDataWhenStatusError, isFalse);
    expect(options.headers['authorization'], 'Bearer $token');
    expect(options.headers['accept'], 'application/json');
  });

  test('quoted UTF-8 application/json content type is accepted', () async {
    final bytes = utf8.encode(jsonEncode(validBody()));
    final outcome = await authorize(
      bytes,
      headers: <String, List<String>>{
        Headers.contentTypeHeader: <String>[
          'application/json; charset="UTF-8"',
        ],
      },
    );

    expect(outcome.result.source, 'identity_https');
    expect(outcome.result.lease, isNotNull);
  });

  test('duplicate every authority-critical member fails on wire', () async {
    const fields = <String>[
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
    ];

    for (final field in fields) {
      final bytes = utf8.encode(duplicateMemberJson(field));
      final outcome = await authorize(bytes);
      expectDenied(outcome.result);
    }
  });

  test('nested duplicate member fails before binding', () async {
    final raw = jsonEncode(validBody()).replaceFirst(
      '"allowed_actions":["device.display_text"]',
      '"allowed_actions":[{"scope":"a","scope":"b"}]',
    );
    final outcome = await authorize(utf8.encode(raw));

    expectDenied(outcome.result);
  });

  test('body byte limit is enforced while streaming', () async {
    final first = Uint8List(HttpMutationAuthorityProvider.maxResponseBytes);
    final second = Uint8List.fromList(<int>[0x7b]);
    final outcome = await authorize(
      const <int>[],
      headers: <String, List<String>>{
        Headers.contentTypeHeader: <String>['application/json'],
      },
      chunks: <Uint8List>[first, second],
    );

    expectDenied(outcome.result);
  });

  test('malformed UTF-8 JSON BOM and trailing data fail closed', () async {
    final valid = utf8.encode(jsonEncode(validBody()));
    final cases = <String, List<int>>{
      'invalid-utf8': <int>[0xff, 0xfe, 0xfd],
      'malformed-json': utf8.encode('{"task_id":'),
      'utf8-bom': <int>[0xef, 0xbb, 0xbf, ...valid],
      'trailing-data': <int>[...valid, ...utf8.encode('{}')],
      'empty': const <int>[],
    };

    for (final entry in cases.entries) {
      final outcome = await authorize(entry.value);
      expectDenied(outcome.result);
    }
  });

  test('missing malformed or ambiguous content type fails closed', () async {
    final bytes = utf8.encode(jsonEncode(validBody()));
    final cases = <String, Map<String, List<String>>>{
      'missing': <String, List<String>>{},
      'wrong-media-type': <String, List<String>>{
        Headers.contentTypeHeader: <String>['text/plain'],
      },
      'multiple-values': <String, List<String>>{
        Headers.contentTypeHeader: <String>[
          'application/json',
          'application/json',
        ],
      },
      'latin1': <String, List<String>>{
        Headers.contentTypeHeader: <String>[
          'application/json; charset=latin-1',
        ],
      },
      'duplicate-charset': <String, List<String>>{
        Headers.contentTypeHeader: <String>[
          'application/json; charset=utf-8; charset=utf-8',
        ],
      },
      'unknown-parameter': <String, List<String>>{
        Headers.contentTypeHeader: <String>[
          'application/json; profile=authority',
        ],
      },
      'malformed-parameter': <String, List<String>>{
        Headers.contentTypeHeader: <String>['application/json; charset'],
      },
    };

    for (final entry in cases.entries) {
      final outcome = await authorize(bytes, headers: entry.value);
      expectDenied(outcome.result);
    }
  });

  test('content length ambiguity mismatch and overflow fail closed', () async {
    final bytes = utf8.encode(jsonEncode(validBody()));
    final cases = <String, Map<String, List<String>>>{
      'multiple-values': <String, List<String>>{
        Headers.contentTypeHeader: <String>['application/json'],
        Headers.contentLengthHeader: <String>[
          '${bytes.length}',
          '${bytes.length}',
        ],
      },
      'negative': <String, List<String>>{
        Headers.contentTypeHeader: <String>['application/json'],
        Headers.contentLengthHeader: <String>['-1'],
      },
      'leading-zero': <String, List<String>>{
        Headers.contentTypeHeader: <String>['application/json'],
        Headers.contentLengthHeader: <String>['0${bytes.length}'],
      },
      'mismatch': <String, List<String>>{
        Headers.contentTypeHeader: <String>['application/json'],
        Headers.contentLengthHeader: <String>['${bytes.length + 1}'],
      },
      'overflow': <String, List<String>>{
        Headers.contentTypeHeader: <String>['application/json'],
        Headers.contentLengthHeader: <String>[
          '${HttpMutationAuthorityProvider.maxResponseBytes + 1}',
        ],
      },
    };

    for (final entry in cases.entries) {
      final outcome = await authorize(bytes, headers: entry.value);
      expectDenied(outcome.result);
    }
  });

  test('non-200 response is unavailable and never decoded', () async {
    final bytes = utf8.encode(jsonEncode(validBody()));
    final outcome = await authorize(bytes, statusCode: 503);

    expectDenied(
      outcome.result,
      source: 'mutation_authority_unavailable',
    );
  });

  test('token provider adapter and stream faults fail closed', () async {
    final throwingTokenProvider = HttpMutationAuthorityProvider(
      baseUri: Uri.parse('https://authority.example/api/'),
      tokenProvider: const _ThrowingTokenProvider(),
      dio: Dio(),
      clock: () => now,
    );
    expectDenied(
      await throwingTokenProvider.authorize(request()),
      source: 'mutation_authority_unavailable',
    );

    final adapterFailure = _StubAdapter(
      (_) => throw StateError('adapter failed'),
    );
    final adapterDio = Dio()..httpClientAdapter = adapterFailure;
    final adapterProvider = HttpMutationAuthorityProvider(
      baseUri: Uri.parse('https://authority.example/api/'),
      tokenProvider: const StaticMutationAccessTokenProvider(token),
      dio: adapterDio,
      clock: () => now,
    );
    expectDenied(
      await adapterProvider.authorize(request()),
      source: 'mutation_authority_unavailable',
    );

    final bytes = utf8.encode(jsonEncode(validBody()));
    final streamFailure = _StubAdapter(
      (_) => ResponseBody(
        Stream<Uint8List>.error(StateError('stream failed')),
        200,
        headers: <String, List<String>>{
          Headers.contentTypeHeader: <String>['application/json'],
          Headers.contentLengthHeader: <String>['${bytes.length}'],
        },
      ),
    );
    final streamDio = Dio()..httpClientAdapter = streamFailure;
    final streamProvider = HttpMutationAuthorityProvider(
      baseUri: Uri.parse('https://authority.example/api/'),
      tokenProvider: const StaticMutationAccessTokenProvider(token),
      dio: streamDio,
      clock: () => now,
    );
    expectDenied(
      await streamProvider.authorize(request()),
      source: 'mutation_authority_unavailable',
    );

    var calls = 0;
    final unstableClock = HttpMutationAuthorityProvider(
      baseUri: Uri.parse('https://authority.example/api/'),
      tokenProvider: const StaticMutationAccessTokenProvider(token),
      dio: Dio(),
      clock: () {
        calls += 1;
        if (calls == 1) {
          throw StateError('clock unavailable');
        }
        return now;
      },
    );
    expectDenied(
      await unstableClock.authorize(request()),
      source: 'mutation_authority_unavailable',
    );
  });
}
