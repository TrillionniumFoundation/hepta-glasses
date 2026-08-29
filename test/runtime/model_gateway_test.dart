import 'package:demo_ai_even/runtime/model_gateway.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('deterministic development gateway returns a bounded answer', () async {
    const gateway = DeterministicModelGateway(prefix: 'test');
    expect(await gateway.answer(question: 'status'), 'test: status');
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
}
