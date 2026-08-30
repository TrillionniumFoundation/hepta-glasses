import 'dart:io';

import 'assistant_session.dart';
import 'audit_journal.dart';
import 'canonical_json.dart';
import 'clock.dart';
import 'contracts.dart';
import 'policy_engine.dart';
import 'tool_gateway.dart';

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

typedef DisplayTextEffect = Future<bool> Function(DisplayTextCommand command);

final class HeptaRuntime {
  HeptaRuntime._({
    required ToolGateway gateway,
    required Clock clock,
    required this.sessions,
  })  : _gateway = gateway,
        _clock = clock;

  static const String _displayTextAction = 'device.display_text';
  static const String _subject = 'local-user';
  static const String _deviceId = 'local-g1-pair';
  static const String _policyHash = 'hepta-edge-policy-v2';

  static HeptaRuntime? _instance;

  final ToolGateway _gateway;
  final Clock _clock;
  final AssistantSessionCoordinator sessions;

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
    AuditJournal? journal,
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
          clock: clock,
        );
    if (effectiveJournal is JsonlAuditJournal) {
      await effectiveJournal.initialize();
    }

    final policy = PolicyEngine(clock: clock);
    final gateway = ToolGateway(
      journal: effectiveJournal,
      policy: policy,
      clock: clock,
    );
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
        final success = await displayTextEffect(
          DisplayTextCommand(
            text: text,
            newScreen: newScreen,
            position: position,
            currentPageNumber: currentPage,
            maxPageNumber: maxPage,
          ),
        );
        if (!success) {
          throw IndeterminateToolEffect(
            'g1-display:${request.idempotencyKey}',
          );
        }
        return <String, Object?>{
          'displayed': true,
          'argument_digest': request.argumentDigest,
        };
      },
      reconciler: (ToolRequest request, String externalId) async =>
          <String, Object?>{
        'authoritative': false,
        'external_id': externalId,
        'reason': 'firmware_display_readback_unavailable',
      },
    );
    await gateway.recover();
    _instance = HeptaRuntime._(
      gateway: gateway,
      clock: clock,
      sessions: AssistantSessionCoordinator(clock: clock),
    );
  }

  Future<ToolReceipt> displayText({
    required AssistantSessionToken session,
    required String text,
    required int newScreen,
    required int position,
    required int currentPageNumber,
    required int maxPageNumber,
  }) {
    final arguments = <String, Object?>{
      'text': text,
      'new_screen': newScreen,
      'position': position,
      'current_page_number': currentPageNumber,
      'max_page_number': maxPageNumber,
    };
    final digest = sha256CanonicalJson(arguments);
    final idempotencyKey =
        'display:${session.sessionId}:${session.generation}:$digest';
    final now = _clock.now();
    final request = ToolRequest(
      requestId: idempotencyKey,
      taskId: session.sessionId,
      deviceId: _deviceId,
      action: _displayTextAction,
      arguments: arguments,
      riskTier: RiskTier.r1,
      mutating: true,
      idempotencyKey: idempotencyKey,
      deadline: now.add(const Duration(seconds: 15)),
      origin: TrustClass.system,
    );
    final lease = DecisionLease(
      leaseId: 'lease:$idempotencyKey',
      subject: _subject,
      taskId: request.taskId,
      deviceId: request.deviceId,
      allowedActions: const <String>{_displayTextAction},
      argumentConstraints: arguments,
      issuedAt: now,
      expiresAt: now.add(const Duration(seconds: 20)),
      singleUse: true,
      policyHash: _policyHash,
    );
    return _gateway.execute(
      request: request,
      context: const PolicyContext(
        subject: _subject,
        authenticated: true,
        userPresent: true,
        biometricVerified: false,
        policyHash: _policyHash,
      ),
      lease: lease,
    );
  }
}
