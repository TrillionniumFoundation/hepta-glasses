import 'package:demo_ai_even/runtime/authenticated_service_tokens.dart';
import 'package:demo_ai_even/runtime/model_gateway.dart';
import 'package:demo_ai_even/runtime/mutation_authority.dart';
import 'package:flutter_test/flutter_test.dart';

final class MutableRuntimeTokenProvider implements RuntimeTokenProvider {
  MutableRuntimeTokenProvider(this.value);

  String? value;

  @override
  Future<String?> getToken() async => value;
}

final class MutableMutationTokenProvider
    implements MutationAccessTokenProvider {
  MutableMutationTokenProvider(this.value);

  String? value;

  @override
  Future<String?> getToken() async => value;
}

void main() {
  tearDown(AuthenticatedServiceTokenRegistry.reset);

  test('one account lifecycle supplies model, speech and mutation providers',
      () async {
    final model = MutableRuntimeTokenProvider('model-token-123456789');
    final mutation = MutableMutationTokenProvider('mutation-token-123456789');

    AuthenticatedServiceTokenRegistry.configure(
      modelAndSpeech: model,
      mutation: mutation,
    );

    const registryModel = RegistryRuntimeTokenProvider();
    const registryMutation = RegistryMutationAccessTokenProvider();
    expect(await registryModel.getToken(), 'model-token-123456789');
    expect(await registryMutation.getToken(), 'mutation-token-123456789');

    model.value = 'rotated-model-token-123456789';
    mutation.value = 'rotated-mutation-token-123456789';
    expect(await registryModel.getToken(), 'rotated-model-token-123456789');
    expect(
      await registryMutation.getToken(),
      'rotated-mutation-token-123456789',
    );
  });

  test('logout or revoke removes every runtime token source', () async {
    AuthenticatedServiceTokenRegistry.configure(
      modelAndSpeech: MutableRuntimeTokenProvider('model-token-123456789'),
      mutation: MutableMutationTokenProvider('mutation-token-123456789'),
    );
    AuthenticatedServiceTokenRegistry.reset();

    expect(await const RegistryRuntimeTokenProvider().getToken(), isNull);
    expect(
      await const RegistryMutationAccessTokenProvider().getToken(),
      isNull,
    );
  });

  test('registry stores providers rather than copying token values', () async {
    final model = MutableRuntimeTokenProvider('first-model-token-123456789');
    final mutation = MutableMutationTokenProvider(
      'first-mutation-token-123456789',
    );
    AuthenticatedServiceTokenRegistry.configure(
      modelAndSpeech: model,
      mutation: mutation,
    );

    model.value = null;
    mutation.value = null;
    expect(await const RegistryRuntimeTokenProvider().getToken(), isNull);
    expect(
      await const RegistryMutationAccessTokenProvider().getToken(),
      isNull,
    );
  });
}
