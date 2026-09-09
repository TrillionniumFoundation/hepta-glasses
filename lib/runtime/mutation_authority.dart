import 'dart:typed_data';

import 'package:dio/dio.dart';

import 'canonical_json.dart';
import 'contracts.dart';
import 'strict_json.dart';

part 'mutation_authority_http.dart';

final class MutationAuthorizationRequest {
  MutationAuthorizationRequest({
    required this.taskId,
    required this.action,
    required Map<String, Object?> arguments,
    required this.riskTier,
    required this.deadline,
  }) : arguments = Map<String, Object?>.unmodifiable(arguments) {
    if (taskId.isEmpty ||
        taskId.length > 256 ||
        action.isEmpty ||
        action.length > 256 ||
        !deadline.isUtc) {
      throw ArgumentError('Invalid mutation authorization request.');
    }
    // Reject unsupported JSON values before an authority request is emitted.
    canonicalJson(this.arguments);
  }

  final String taskId;
  final String action;
  final Map<String, Object?> arguments;
  final RiskTier riskTier;
  final DateTime deadline;
}

final class MutationAuthorization {
  const MutationAuthorization({
    required this.deviceId,
    required this.context,
    required this.lease,
    required this.source,
  });

  final String deviceId;
  final PolicyContext context;
  final DecisionLease? lease;
  final String source;
}

abstract interface class MutationAuthorityProvider {
  Future<MutationAuthorization> authorize(
    MutationAuthorizationRequest request,
  );
}

final class FailClosedMutationAuthorityProvider
    implements MutationAuthorityProvider {
  const FailClosedMutationAuthorityProvider([this.reason = 'fail_closed']);

  final String reason;

  @override
  Future<MutationAuthorization> authorize(
    MutationAuthorizationRequest request,
  ) async =>
      MutationAuthorization(
        deviceId: 'unbound-device',
        context: const PolicyContext(
          subject: 'unauthenticated',
          authenticated: false,
          userPresent: false,
          biometricVerified: false,
          policyHash: 'unavailable',
        ),
        lease: null,
        source: reason,
      );
}

abstract interface class MutationAccessTokenProvider {
  Future<String?> getToken();
}

final class UnavailableMutationAccessTokenProvider
    implements MutationAccessTokenProvider {
  const UnavailableMutationAccessTokenProvider();

  @override
  Future<String?> getToken() async => null;
}

final class StaticMutationAccessTokenProvider
    implements MutationAccessTokenProvider {
  const StaticMutationAccessTokenProvider(this.token);

  final String? token;

  @override
  Future<String?> getToken() async => token;
}

/// Mutable only through authenticated application composition after login.
///
/// The registry contains a provider, never a cached bearer token. Logging out or
/// revoking the account must replace it with the unavailable provider.
final class MutationAccessTokenRegistry {
  MutationAccessTokenRegistry._();

  static MutationAccessTokenProvider _current =
      const UnavailableMutationAccessTokenProvider();

  static MutationAccessTokenProvider get current => _current;

  static void configure(MutationAccessTokenProvider provider) {
    _current = provider;
  }

  static void reset() {
    _current = const UnavailableMutationAccessTokenProvider();
  }
}

final class RegistryMutationAccessTokenProvider
    implements MutationAccessTokenProvider {
  const RegistryMutationAccessTokenProvider();

  @override
  Future<String?> getToken() => MutationAccessTokenRegistry.current.getToken();
}

final class MutationAuthorityRegistry {
  MutationAuthorityRegistry._();

  static MutationAuthorityProvider _current =
      const FailClosedMutationAuthorityProvider();

  static MutationAuthorityProvider get current => _current;

  static void configure(MutationAuthorityProvider provider) {
    _current = provider;
  }

  static void reset() {
    _current = const FailClosedMutationAuthorityProvider();
  }
}

final class MutationAuthorityBootstrap {
  MutationAuthorityBootstrap._();

  static void configureFromEnvironment() {
    const url = String.fromEnvironment(
      'HEPTA_MUTATION_AUTHORITY_URL',
    );
    const developmentToken = String.fromEnvironment(
      'HEPTA_MUTATION_AUTHORITY_DEV_TOKEN',
    );
    const product = bool.fromEnvironment('dart.vm.product');

    if (product && developmentToken.isNotEmpty) {
      MutationAuthorityRegistry.configure(
        const FailClosedMutationAuthorityProvider(
          'compiled_mutation_token_forbidden_in_product',
        ),
      );
      return;
    }
    if (url.isEmpty) {
      MutationAuthorityRegistry.reset();
      return;
    }
    final uri = Uri.tryParse(url);
    if (uri == null || !uri.hasScheme || uri.host.isEmpty) {
      MutationAuthorityRegistry.configure(
        const FailClosedMutationAuthorityProvider(
          'invalid_mutation_authority_url',
        ),
      );
      return;
    }
    final tokenProvider = !product && developmentToken.isNotEmpty
        ? const StaticMutationAccessTokenProvider(developmentToken)
        : const RegistryMutationAccessTokenProvider();
    try {
      MutationAuthorityRegistry.configure(
        HttpMutationAuthorityProvider(
          baseUri: uri,
          tokenProvider: tokenProvider,
          allowInsecureLoopback: !product,
        ),
      );
    } on ArgumentError {
      MutationAuthorityRegistry.configure(
        const FailClosedMutationAuthorityProvider(
          'insecure_mutation_authority_url',
        ),
      );
    }
  }
}
