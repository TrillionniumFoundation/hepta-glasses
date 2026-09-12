import 'model_gateway.dart';
import 'mutation_authority.dart';

/// Account/session code installs providers after authenticated login and resets
/// them on logout, device/session revoke, or attestation loss. This registry
/// stores providers, not bearer-token bytes.
final class AuthenticatedServiceTokenRegistry {
  AuthenticatedServiceTokenRegistry._();

  static RuntimeTokenProvider _modelAndSpeech =
      const StaticRuntimeTokenProvider(null);
  static MutationAccessTokenProvider _mutation =
      const UnavailableMutationAccessTokenProvider();

  static RuntimeTokenProvider get modelAndSpeech => _modelAndSpeech;
  static MutationAccessTokenProvider get mutation => _mutation;

  static void configure({
    required RuntimeTokenProvider modelAndSpeech,
    required MutationAccessTokenProvider mutation,
  }) {
    _modelAndSpeech = modelAndSpeech;
    _mutation = mutation;
    MutationAccessTokenRegistry.configure(mutation);
  }

  static void reset() {
    _modelAndSpeech = const StaticRuntimeTokenProvider(null);
    _mutation = const UnavailableMutationAccessTokenProvider();
    MutationAccessTokenRegistry.reset();
  }
}

final class RegistryRuntimeTokenProvider implements RuntimeTokenProvider {
  const RegistryRuntimeTokenProvider();

  @override
  Future<String?> getToken() =>
      AuthenticatedServiceTokenRegistry.modelAndSpeech.getToken();
}

/// Replaces development-only model/speech clients with runtime-token clients
/// whenever a production endpoint is configured.
final class AuthenticatedServiceBootstrap {
  AuthenticatedServiceBootstrap._();

  static void configureFromEnvironment() {
    const modelUrl = String.fromEnvironment('HEPTA_MODEL_GATEWAY_URL');
    const speechUrl = String.fromEnvironment('HEPTA_SPEECH_BOOTSTRAP_URL');
    const modelDevToken =
        String.fromEnvironment('HEPTA_MODEL_GATEWAY_DEV_TOKEN');
    const speechDevToken =
        String.fromEnvironment('HEPTA_SPEECH_BOOTSTRAP_DEV_TOKEN');
    const product = bool.fromEnvironment('dart.vm.product');

    if (product && (modelDevToken.isNotEmpty || speechDevToken.isNotEmpty)) {
      ModelGatewayRegistry.configure(
        const UnavailableModelGateway('compiled_token_forbidden_in_product'),
      );
      SpeechBootstrapGatewayRegistry.configure(
        const UnavailableSpeechBootstrapGateway(
          'compiled_speech_token_forbidden_in_product',
        ),
      );
      return;
    }

    final tokenProvider = product
        ? const RegistryRuntimeTokenProvider()
        : StaticRuntimeTokenProvider(
            modelDevToken.isNotEmpty
                ? modelDevToken
                : speechDevToken.isNotEmpty
                    ? speechDevToken
                    : null,
          );

    if (modelUrl.isNotEmpty) {
      final uri = Uri.tryParse(modelUrl);
      if (uri == null || !uri.hasScheme || uri.host.isEmpty) {
        ModelGatewayRegistry.configure(
          const UnavailableModelGateway('invalid_gateway_url'),
        );
      } else {
        try {
          ModelGatewayRegistry.configure(
            HttpModelGateway(
              baseUri: uri,
              tokenProvider: tokenProvider,
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

    if (speechUrl.isNotEmpty) {
      final uri = Uri.tryParse(speechUrl);
      if (uri == null || !uri.hasScheme || uri.host.isEmpty) {
        SpeechBootstrapGatewayRegistry.configure(
          const UnavailableSpeechBootstrapGateway(
            'invalid_speech_bootstrap_url',
          ),
        );
      } else {
        try {
          SpeechBootstrapGatewayRegistry.configure(
            HttpSpeechBootstrapGateway(
              baseUri: uri,
              tokenProvider: tokenProvider,
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
  }
}
