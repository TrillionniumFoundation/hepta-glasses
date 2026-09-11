import 'package:demo_ai_even/runtime/model_gateway.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('deterministic development gateway returns a bounded answer', () async {
    const gateway = DeterministicModelGateway(prefix: 'test');
    expect(await gateway.answer(question: 'status'), 'test: status');
  });

  test('model requests observe cancellation before execution', () async {
    const gateway = DeterministicModelGateway(prefix: 'test');
    final cancellation = ModelRequestCancellation()..cancel('session-ended');

    await expectLater(
      gateway.answer(question: 'status', cancellation: cancellation),
      throwsA(
        isA<ModelGatewayException>().having(
          (ModelGatewayException error) => error.code,
          'code',
          'model_request_cancelled',
        ),
      ),
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

  test('speech bootstrap is bound to session, generation, pair and locale', () {
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
    expect(bootstrap.pairIdentity, 'Pair_7');
    expect(bootstrap.toNativeArguments()['bearerToken'], isNotEmpty);
  });

  test('speech bootstrap rejects authority drift and excessive lifetime', () {
    final value = <String, Object?>{
      'bootstrap_id': 'bootstrap-1',
      'session_id': 'session-1',
      'generation': 9,
      'pair_identity': 'Pair_7',
      'locale': 'en-US',
      'endpoint': 'https://speech.example/v1/asr',
      'bearer_token': 'ephemeral-token-123456789',
      'provider': 'speech-provider',
      'expires_at': 500,
      'maximum_audio_bytes': 6400,
    };

    expect(
      () => SpeechBootstrap.fromMap(
        value,
        expectedSessionId: 'session-1',
        expectedGeneration: 10,
        expectedPairIdentity: 'Pair_7',
        expectedLocale: 'en-US',
        nowEpochSeconds: 100,
      ),
      throwsA(isA<SpeechBootstrapException>()),
    );
    expect(
      () => SpeechBootstrap.fromMap(
        value,
        expectedSessionId: 'session-1',
        expectedGeneration: 9,
        expectedPairIdentity: 'Pair_7',
        expectedLocale: 'en-US',
        nowEpochSeconds: 100,
      ),
      throwsA(
        isA<SpeechBootstrapException>().having(
          (SpeechBootstrapException error) => error.code,
          'code',
          'speech_bootstrap_expired',
        ),
      ),
    );
  });

  test('speech bootstrap rejects non-HTTPS provider endpoints', () {
    expect(
      () => SpeechBootstrap.fromMap(
        <String, Object?>{
          'bootstrap_id': 'bootstrap-1',
          'session_id': 'session-1',
          'generation': 9,
          'pair_identity': 'Pair_7',
          'locale': 'en-US',
          'endpoint': 'http://speech.example/v1/asr',
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
      ),
      throwsA(
        isA<SpeechBootstrapException>().having(
          (SpeechBootstrapException error) => error.code,
          'code',
          'speech_bootstrap_endpoint_invalid',
        ),
      ),
    );
  });
}
