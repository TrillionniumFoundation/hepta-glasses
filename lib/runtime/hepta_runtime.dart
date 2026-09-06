import 'dart:io';

import 'assistant_session.dart';
import 'audit_checkpoint_authenticator.dart';
import 'audit_journal.dart';
import 'canonical_json.dart';
import 'clock.dart';
import 'contracts.dart';
import 'device_effect_result.dart';
import 'device_effect_scheduler.dart';
import 'mutation_authority.dart';
import 'policy_engine.dart';
import 'tool_gateway.dart';

final class RuntimeEffectScope {
  const RuntimeEffectScope({required this.scopeId, required this.generation});

  factory RuntimeEffectScope.assistant(AssistantSessionToken session) =>
      RuntimeEffectScope(
        scopeId: session.sessionId,
        generation: session.generation,
      );

  final String scopeId;
  final int generation;
}

final class DisplayTextCommand {
  const DisplayTextCommand({
    required this.text,
    required this.newScreen,
    required this.position,
    required this.currentPageNumber,
    required this.maxPageNumber,
  });

  final String text;
  final int newScreen;
  final int position;
  final int currentPageNumber;
  final int maxPageNumber;
}

typedef DisplayTextEffect = Future<DeviceEffectResult> Function(
  DisplayTextCommand command,
);
typedef MicrophoneEffect = Future<DeviceEffectResult> Function(String side);
typedef ExitDeviceModeEffect = Future<DeviceEffectResult> Function();
typedef NotificationWhitelistEffect = Future<DeviceEffectResult> Function(
  String document,
);
typedef NotificationEffect = Future<DeviceEffectResult> Function(
  Map<String, Object?> notification,
  int notificationId,
);
typedef BitmapAssetEffect = Future<DeviceEffectResult> Function(
    String assetPath);

final class HeptaRuntime {
  HeptaRuntime._({
    required ToolGateway gateway,
    required Clock clock,
    required MutationAuthorityProvider mutationAuthority,
    required this.sessions,
  })  : _gateway = gateway,
        _clock = clock,
        _mutationAuthority = mutationAuthority;

  static const String _displayTextAction = 'device.display_text';
  static const String _microphoneOnAction = 'device.microphone_on';
  static const String _exitModeAction = 'device.exit_mode';
  static const String _notificationWhitelistAction =
      'device.notification_whitelist';
  static const String _notificationAction = 'device.send_notification';
  static const String _bitmapAction = 'device.display_bitmap_asset';

  static HeptaRuntime? _instance;

  final ToolGateway _gateway;
  final Clock _clock;
  final MutationAuthorityProvider _mutationAuthority;
  final AssistantSessionCoordinator sessions;
  int _scopeGeneration = 0;

  static bool get isInitialized => _instance != null;

  static HeptaRuntime get current {
    final runtime = _instance;
    if (runtime == null) {
      throw StateError('HeptaRuntime has not been initialized.');
    }
    return runtime;
  }

  static Future<void> initialize({
    required DisplayTextEffect displayTextEffect,
    required MicrophoneEffect microphoneEffect,
    required ExitDeviceModeEffect exitDeviceModeEffect,
    required NotificationWhitelistEffect notificationWhitelistEffect,
    required NotificationEffect notificationEffect,
    required BitmapAssetEffect bitmapAssetEffect,
    required MutationAuthorityProvider mutationAuthority,
    AuditJournal? journal,
    DeviceEffectScheduler? effectScheduler,
    Clock clock = const SystemClock(),
  }) async {
    if (_instance != null) {
      return;
    }
    final effectiveJournal = journal ??
        JsonlAuditJournal(
          File(
            '${Directory.systemTemp.path}/hepta-glasses-runtime/audit.jsonl',
          ),
          checkpointAuthenticator: const PlatformAuditCheckpointAuthenticator(),
          clock: clock,
        );
    if (effectiveJournal is JsonlAuditJournal) {
      await effectiveJournal.initialize();
    }

    final scheduler = effectScheduler ?? DeviceEffectScheduler();
    final policy = PolicyEngine(clock: clock);
    final gateway = ToolGateway(
      journal: effectiveJournal,
      policy: policy,
      clock: clock,
    );

    Future<Map<String, Object?>> applyDeviceEffect(
      ToolRequest request,
      Future<DeviceEffectResult> Function() effect,
    ) async {
      final remaining = request.deadline.difference(clock.now());
      if (remaining <= Duration.zero) {
        throw IndeterminateToolEffect(
          '${request.action}:${request.idempotencyKey}',
          code: 'effect_deadline_elapsed_before_schedule',
        );
      }
      final DeviceEffectResult outcome;
      try {
        outcome = await scheduler.schedule(
          request.action,
          effect,
          executionTimeout: remaining,
        );
      } on DeviceEffectTimeoutException catch (error) {
        throw IndeterminateToolEffect(
          '${request.action}:${request.idempotencyKey}',
          code: 'effect_scheduler_timeout',
          details: <String, Object?>{
            'operation': error.operation,
            'timeout_ms': error.timeout.inMilliseconds,
          },
        );
      }
      switch (outcome.disposition) {
        case DeviceEffectDisposition.committed:
          return <String, Object?>{
            'applied': true,
            'argument_digest': request.argumentDigest,
            ...outcome.toResultJson(),
          };
        case DeviceEffectDisposition.rejectedBeforeWrite:
          throw RejectedToolEffect(
            outcome.code,
            externalId: outcome.externalId,
            details: outcome.details,
          );
        case DeviceEffectDisposition.indeterminate:
          throw IndeterminateToolEffect(
            outcome.externalId ?? '${request.action}:${request.idempotencyKey}',
            code: outcome.code,
            details: outcome.details,
          );
      }
    }

    Map<String, Object?> unavailableReconciliation(
      String externalId,
      String reason,
    ) =>
        <String, Object?>{
          'authoritative': false,
          'external_id': externalId,
          'reason': reason,
        };

    gateway.register(
      const ToolSpec(
        action: _displayTextAction,
        riskTier: RiskTier.r1,
        mutating: true,
      ),
      (ToolRequest request) async {
        final arguments = request.arguments;
        final text = arguments['text'];
        final newScreen = arguments['new_screen'];
        final position = arguments['position'];
        final currentPage = arguments['current_page_number'];
        final maxPage = arguments['max_page_number'];
        if (text is! String ||
            newScreen is! int ||
            position is! int ||
            currentPage is! int ||
            maxPage is! int) {
          throw const FormatException('display_text_arguments_invalid');
        }
        return applyDeviceEffect(
          request,
          () => displayTextEffect(
            DisplayTextCommand(
              text: text,
              newScreen: newScreen,
              position: position,
              currentPageNumber: currentPage,
              maxPageNumber: maxPage,
            ),
          ),
        );
      },
      reconciler: (ToolRequest request, String externalId) async =>
          unavailableReconciliation(
        externalId,
        'firmware_display_readback_unavailable',
      ),
      recoveryReconciler:
          (ToolAuditEnvelope request, String externalId) async =>
              unavailableReconciliation(
        externalId,
        'firmware_display_readback_unavailable',
      ),
    );

    gateway.register(
      const ToolSpec(
        action: _microphoneOnAction,
        riskTier: RiskTier.r2,
        mutating: true,
      ),
      (ToolRequest request) async {
        final side = request.arguments['side'];
        final attempt = request.arguments['attempt'];
        if (side is! String ||
            !<String>{'L', 'R'}.contains(side) ||
            attempt is! int ||
            attempt < 1 ||
            attempt > 3) {
          throw const FormatException('microphone_arguments_invalid');
        }
        return applyDeviceEffect(request, () => microphoneEffect(side));
      },
      reconciler: (ToolRequest request, String externalId) async =>
          unavailableReconciliation(
        externalId,
        'microphone_state_readback_unavailable',
      ),
      recoveryReconciler:
          (ToolAuditEnvelope request, String externalId) async =>
              unavailableReconciliation(
        externalId,
        'microphone_state_readback_unavailable',
      ),
    );

    gateway.register(
      const ToolSpec(
        action: _exitModeAction,
        riskTier: RiskTier.r1,
        mutating: true,
      ),
      (ToolRequest request) => applyDeviceEffect(request, exitDeviceModeEffect),
      reconciler: (ToolRequest request, String externalId) async =>
          unavailableReconciliation(
        externalId,
        'device_mode_readback_unavailable',
      ),
      recoveryReconciler:
          (ToolAuditEnvelope request, String externalId) async =>
              unavailableReconciliation(
        externalId,
        'device_mode_readback_unavailable',
      ),
    );

    gateway.register(
      const ToolSpec(
        action: _notificationWhitelistAction,
        riskTier: RiskTier.r2,
        mutating: true,
      ),
      (ToolRequest request) async {
        final document = request.arguments['document'];
        if (document is! String || document.length > 32768) {
          throw const FormatException('notification_whitelist_invalid');
        }
        return applyDeviceEffect(
          request,
          () => notificationWhitelistEffect(document),
        );
      },
      reconciler: (ToolRequest request, String externalId) async =>
          unavailableReconciliation(
        externalId,
        'notification_whitelist_readback_unavailable',
      ),
      recoveryReconciler:
          (ToolAuditEnvelope request, String externalId) async =>
              unavailableReconciliation(
        externalId,
        'notification_whitelist_readback_unavailable',
      ),
    );

    gateway.register(
      const ToolSpec(
        action: _notificationAction,
        riskTier: RiskTier.r1,
        mutating: true,
      ),
      (ToolRequest request) async {
        final rawNotification = request.arguments['notification'];
        final notificationId = request.arguments['notification_id'];
        if (rawNotification is! Map || notificationId is! int) {
          throw const FormatException('notification_arguments_invalid');
        }
        final notification = rawNotification.map(
          (key, value) => MapEntry(key.toString(), value as Object?),
        );
        return applyDeviceEffect(
          request,
          () => notificationEffect(notification, notificationId),
        );
      },
      reconciler: (ToolRequest request, String externalId) async =>
          unavailableReconciliation(
        externalId,
        'notification_delivery_readback_unavailable',
      ),
      recoveryReconciler:
          (ToolAuditEnvelope request, String externalId) async =>
              unavailableReconciliation(
        externalId,
        'notification_delivery_readback_unavailable',
      ),
    );

    gateway.register(
      const ToolSpec(
        action: _bitmapAction,
        riskTier: RiskTier.r1,
        mutating: true,
      ),
      (ToolRequest request) async {
        final assetPath = request.arguments['asset_path'];
        if (assetPath is! String ||
            !RegExp(r'^assets/images/[A-Za-z0-9._-]+[.]bmp$')
                .hasMatch(assetPath)) {
          throw const FormatException('bitmap_asset_path_invalid');
        }
        return applyDeviceEffect(request, () => bitmapAssetEffect(assetPath));
      },
      reconciler: (ToolRequest request, String externalId) async =>
          unavailableReconciliation(
        externalId,
        'bitmap_crc_readback_unavailable_after_session',
      ),
      recoveryReconciler:
          (ToolAuditEnvelope request, String externalId) async =>
              unavailableReconciliation(
        externalId,
        'bitmap_crc_readback_unavailable_after_session',
      ),
    );

    await gateway.recover();
    _instance = HeptaRuntime._(
      gateway: gateway,
      clock: clock,
      mutationAuthority: mutationAuthority,
      sessions: AssistantSessionCoordinator(clock: clock),
    );
  }

  RuntimeEffectScope beginEffectScope(String prefix) {
    if (!RegExp(r'^[a-z][a-z0-9-]{1,31}$').hasMatch(prefix)) {
      throw ArgumentError.value(
        prefix,
        'prefix',
        'is not a bounded scope name',
      );
    }
    _scopeGeneration++;
    return RuntimeEffectScope(
      scopeId:
          '$prefix-${_clock.now().microsecondsSinceEpoch}-$_scopeGeneration',
      generation: _scopeGeneration,
    );
  }

  Future<ToolReceipt> displayText({
    required AssistantSessionToken session,
    required String text,
    required int newScreen,
    required int position,
    required int currentPageNumber,
    required int maxPageNumber,
  }) =>
      displayTextInScope(
        scope: RuntimeEffectScope.assistant(session),
        text: text,
        newScreen: newScreen,
        position: position,
        currentPageNumber: currentPageNumber,
        maxPageNumber: maxPageNumber,
        origin: TrustClass.system,
      );

  Future<ToolReceipt> displayTextInScope({
    required RuntimeEffectScope scope,
    required String text,
    required int newScreen,
    required int position,
    required int currentPageNumber,
    required int maxPageNumber,
    TrustClass origin = TrustClass.user,
  }) =>
      _executeMutation(
        scope: scope,
        action: _displayTextAction,
        riskTier: RiskTier.r1,
        arguments: <String, Object?>{
          'text': text,
          'new_screen': newScreen,
          'position': position,
          'current_page_number': currentPageNumber,
          'max_page_number': maxPageNumber,
        },
        origin: origin,
      );

  Future<ToolReceipt> openMicrophone({
    required AssistantSessionToken session,
    String side = 'R',
    int attempt = 1,
  }) =>
      _executeMutation(
        scope: RuntimeEffectScope.assistant(session),
        action: _microphoneOnAction,
        riskTier: RiskTier.r2,
        arguments: <String, Object?>{
          'side': side,
          'attempt': attempt,
        },
        origin: TrustClass.user,
      );

  Future<ToolReceipt> exitDeviceMode({required RuntimeEffectScope scope}) =>
      _executeMutation(
        scope: scope,
        action: _exitModeAction,
        riskTier: RiskTier.r1,
        arguments: const <String, Object?>{},
      );

  Future<ToolReceipt> setNotificationWhitelist({
    required RuntimeEffectScope scope,
    required String document,
  }) =>
      _executeMutation(
        scope: scope,
        action: _notificationWhitelistAction,
        riskTier: RiskTier.r2,
        arguments: <String, Object?>{'document': document},
      );

  Future<ToolReceipt> sendNotification({
    required RuntimeEffectScope scope,
    required Map<String, Object?> notification,
    required int notificationId,
    TrustClass origin = TrustClass.user,
    String? humanConfirmationDigest,
  }) =>
      _executeMutation(
        scope: scope,
        action: _notificationAction,
        riskTier: RiskTier.r1,
        arguments: <String, Object?>{
          'notification': notification,
          'notification_id': notificationId,
        },
        origin: origin,
        humanConfirmationDigest: humanConfirmationDigest,
      );

  Future<ToolReceipt> displayBitmapAsset({
    required RuntimeEffectScope scope,
    required String assetPath,
  }) =>
      _executeMutation(
        scope: scope,
        action: _bitmapAction,
        riskTier: RiskTier.r1,
        arguments: <String, Object?>{'asset_path': assetPath},
        deadline: const Duration(minutes: 2),
      );

  Future<ToolReceipt> reconcileEffect(String idempotencyKey) =>
      _gateway.reconcile(idempotencyKey: idempotencyKey);

  Future<ToolReceipt> _executeMutation({
    required RuntimeEffectScope scope,
    required String action,
    required RiskTier riskTier,
    required Map<String, Object?> arguments,
    TrustClass origin = TrustClass.user,
    String? humanConfirmationDigest,
    Duration deadline = const Duration(seconds: 20),
  }) async {
    final digest = sha256CanonicalJson(arguments);
    final now = _clock.now();
    final expiresAt = now.add(deadline);
    final authorization = await _mutationAuthority.authorize(
      MutationAuthorizationRequest(
        taskId: scope.scopeId,
        action: action,
        arguments: arguments,
        riskTier: riskTier,
        deadline: expiresAt,
      ),
    );
    final idempotencyKey = '$action:${authorization.deviceId}:${scope.scopeId}:'
        '${scope.generation}:$digest';
    final request = ToolRequest(
      requestId: idempotencyKey,
      taskId: scope.scopeId,
      deviceId: authorization.deviceId,
      action: action,
      arguments: arguments,
      riskTier: riskTier,
      mutating: true,
      idempotencyKey: idempotencyKey,
      deadline: expiresAt,
      origin: origin,
      humanConfirmationDigest: humanConfirmationDigest,
    );
    return _gateway.execute(
      request: request,
      context: authorization.context,
      lease: authorization.lease,
    );
  }
}
