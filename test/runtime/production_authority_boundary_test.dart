import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  const forbiddenProductTokens = <String>[
    'HEPTA_ALLOW_DEVELOPMENT_AUTHORITY',
    'DevelopmentMutationAuthorityProvider',
    'explicit-development-build-flag',
    'development_build_flag',
    'dev-lease-',
    'development-user',
    'development-g1-pair',
    'TestMutationAuthorityProvider',
    'test-only-authority',
    'test-lease-',
  ];

  test('production mobile graph excludes test-only mutation authority', () {
    final productFiles = Directory('lib')
        .listSync(recursive: true)
        .whereType<File>()
        .where((File file) => file.path.endsWith('.dart'))
        .toList(growable: false)
      ..sort((File left, File right) => left.path.compareTo(right.path));
    final productSource =
        productFiles.map((File file) => file.readAsStringSync()).join('\n');

    for (final token in forbiddenProductTokens) {
      expect(
        productSource,
        isNot(contains(token)),
        reason: 'forbidden product authority token: $token',
      );
    }

    final mainSource = File('lib/main.dart').readAsStringSync();
    for (final required in <String>[
      'AuthenticatedServiceBootstrap.configureFromEnvironment();',
      'MutationAuthorityBootstrap.configureFromEnvironment();',
      'mutationAuthority: MutationAuthorityRegistry.current,',
    ]) {
      expect(mainSource, contains(required));
    }
    for (final forbidden in <String>[
      'ModelGatewayBootstrap.configureFromDevelopmentEnvironment();',
      'SpeechBootstrapBootstrap.configureFromDevelopmentEnvironment();',
      'mutationAuthority: const FailClosedMutationAuthorityProvider(),',
    ]) {
      expect(mainSource, isNot(contains(forbidden)));
    }

    final serviceTokensSource =
        File('lib/runtime/authenticated_service_tokens.dart')
            .readAsStringSync();
    for (final required in <String>[
      'class AuthenticatedServiceTokenRegistry',
      'class RegistryRuntimeTokenProvider',
      'class AuthenticatedServiceBootstrap',
      "bool.fromEnvironment('dart.vm.product')",
      'compiled_token_forbidden_in_product',
      'compiled_speech_token_forbidden_in_product',
      'SpeechBootstrapGatewayRegistry.configure(',
    ]) {
      expect(serviceTokensSource, contains(required));
    }

    final bootstrapSource =
        File('lib/bootstrap/hepta_bootstrap.dart').readAsStringSync();
    expect(
      bootstrapSource,
      contains('required MutationAuthorityProvider mutationAuthority'),
    );
    expect(bootstrapSource, isNot(contains('bool.fromEnvironment')));

    final testAuthority = File('test/support/test_mutation_authority.dart');
    expect(testAuthority.existsSync(), isTrue);
    expect(testAuthority.path.startsWith('test/'), isTrue);
  });
}
