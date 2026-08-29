import 'audit_journal.dart';
import 'clock.dart';
import 'contracts.dart';
import 'policy_engine.dart';

typedef ToolHandler = Future<Map<String, Object?>> Function(
  ToolRequest request,
);

final class ToolGateway {
  ToolGateway({
    required AuditJournal journal,
    required PolicyEngine policy,
    Clock clock = const SystemClock(),
  })  : _journal = journal,
        _policy = policy,
        _clock = clock;

  final AuditJournal _journal;
  final PolicyEngine _policy;
  final Clock _clock;
  final Map<String, ToolSpec> _specs = <String, ToolSpec>{};
  final Map<String, ToolHandler> _handlers = <String, ToolHandler>{};
  final Map<String, ToolReceipt> _receipts = <String, ToolReceipt>{};
  final Map<String, String> _fingerprints = <String, String>{};

  void register(ToolSpec spec, ToolHandler handler) {
    if (_specs.containsKey(spec.action)) {
      throw StateError('Tool ${spec.action} is already registered.');
    }
    _specs[spec.action] = spec;
    _handlers[spec.action] = handler;
  }

  List<ToolSpec> get tools => List.unmodifiable(_specs.values);

  ToolReceipt? receiptFor(String idempotencyKey) => _receipts[idempotencyKey];

  Future<ToolReceipt> execute({
    required ToolRequest request,
    required PolicyContext context,
    DecisionLease? lease,
  }) async {
    final existing = _receipts[request.idempotencyKey];
    if (existing != null) {
      if (_fingerprints[request.idempotencyKey] != request.fingerprint) {
        throw StateError(
          'Idempotency key was reused with different tool request data.',
        );
      }
      return existing.asReplay();
    }

    final startedAt = _clock.now();
    if (!startedAt.isBefore(request.deadline)) {
      return _finalizeWithoutEffect(
        request: request,
        startedAt: startedAt,
        status: ToolReceiptStatus.rejected,
        policyReason: 'request_deadline_expired',
      );
    }

    final spec = _specs[request.action];
    final handler = _handlers[request.action];
    if (spec == null || handler == null) {
      return _finalizeWithoutEffect(
        request: request,
        startedAt: startedAt,
        status: ToolReceiptStatus.rejected,
        policyReason: 'tool_not_registered',
      );
    }

    final decision = _policy.evaluate(
      spec: spec,
      request: request,
      context: context,
      lease: lease,
    );
    await _journal.append('tool.decision', <String, Object?>{
      'request_id': request.requestId,
      'task_id': request.taskId,
      'action': request.action,
      'idempotency_key': request.idempotencyKey,
      'request_fingerprint': request.fingerprint,
      'decision': decision.toJson(),
    });
    if (!decision.allowed) {
      return _cacheReceipt(
        request: request,
        receipt: ToolReceipt(
          requestId: request.requestId,
          idempotencyKey: request.idempotencyKey,
          status: ToolReceiptStatus.rejected,
          policyReason: decision.reason,
          result: const <String, Object?>{},
          startedAt: startedAt,
          completedAt: _clock.now(),
        ),
      );
    }

    if (request.mutating) {
      await _journal.append('tool.prepared', <String, Object?>{
        'request': request.toJson(),
        'request_fingerprint': request.fingerprint,
        'lease_id': lease?.leaseId,
      });
    }
    _policy.consume(lease);

    try {
      final result = await handler(request);
      final completedAt = _clock.now();
      if (request.mutating) {
        await _journal.append('tool.completed', <String, Object?>{
          'request_id': request.requestId,
          'idempotency_key': request.idempotencyKey,
          'result': result,
        });
      } else {
        await _journal.append('tool.observed', <String, Object?>{
          'request_id': request.requestId,
          'action': request.action,
        });
      }
      return _cacheReceipt(
        request: request,
        receipt: ToolReceipt(
          requestId: request.requestId,
          idempotencyKey: request.idempotencyKey,
          status: ToolReceiptStatus.succeeded,
          policyReason: decision.reason,
          result: Map.unmodifiable(result),
          startedAt: startedAt,
          completedAt: completedAt,
        ),
      );
    } on Object catch (error) {
      await _journal.append('tool.failed', <String, Object?>{
        'request_id': request.requestId,
        'idempotency_key': request.idempotencyKey,
        'error_type': error.runtimeType.toString(),
      });
      return _cacheReceipt(
        request: request,
        receipt: ToolReceipt(
          requestId: request.requestId,
          idempotencyKey: request.idempotencyKey,
          status: ToolReceiptStatus.failed,
          policyReason: decision.reason,
          result: <String, Object?>{
            'error': 'tool_execution_failed',
          },
          startedAt: startedAt,
          completedAt: _clock.now(),
        ),
      );
    }
  }

  Future<ToolReceipt> _finalizeWithoutEffect({
    required ToolRequest request,
    required DateTime startedAt,
    required ToolReceiptStatus status,
    required String policyReason,
  }) async {
    await _journal.append('tool.rejected', <String, Object?>{
      'request_id': request.requestId,
      'action': request.action,
      'idempotency_key': request.idempotencyKey,
      'reason': policyReason,
    });
    return _cacheReceipt(
      request: request,
      receipt: ToolReceipt(
        requestId: request.requestId,
        idempotencyKey: request.idempotencyKey,
        status: status,
        policyReason: policyReason,
        result: const <String, Object?>{},
        startedAt: startedAt,
        completedAt: _clock.now(),
      ),
    );
  }

  ToolReceipt _cacheReceipt({
    required ToolRequest request,
    required ToolReceipt receipt,
  }) {
    _fingerprints[request.idempotencyKey] = request.fingerprint;
    _receipts[request.idempotencyKey] = receipt;
    return receipt;
  }
}
