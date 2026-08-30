import 'audit_journal.dart';
import 'clock.dart';
import 'contracts.dart';
import 'policy_engine.dart';

typedef ToolHandler = Future<Map<String, Object?>> Function(
  ToolRequest request,
);

typedef ToolReconciler = Future<Map<String, Object?>> Function(
  ToolRequest request,
  String externalId,
);

final class IndeterminateToolEffect implements Exception {
  const IndeterminateToolEffect(this.externalId);

  final String externalId;

  @override
  String toString() => 'IndeterminateToolEffect($externalId)';
}

final class _PreparedTool {
  const _PreparedTool({required this.request, required this.startedAt});

  final ToolRequest request;
  final DateTime startedAt;
}

Map<String, Object?> _objectMap(Object? value, String label) {
  if (value is! Map) {
    throw StateError('$label must be an object.');
  }
  return value.map(
    (key, item) => MapEntry(key.toString(), item as Object?),
  );
}

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
  final Map<String, ToolReconciler> _reconcilers = <String, ToolReconciler>{};
  final Map<String, ToolReceipt> _receipts = <String, ToolReceipt>{};
  final Map<String, String> _fingerprints = <String, String>{};
  final Map<String, ToolRequest> _requests = <String, ToolRequest>{};

  void register(
    ToolSpec spec,
    ToolHandler handler, {
    ToolReconciler? reconciler,
  }) {
    if (_specs.containsKey(spec.action)) {
      throw StateError('Tool ${spec.action} is already registered.');
    }
    _specs[spec.action] = spec;
    _handlers[spec.action] = handler;
    if (reconciler != null) {
      _reconcilers[spec.action] = reconciler;
    }
  }

  List<ToolSpec> get tools => List.unmodifiable(_specs.values);

  ToolReceipt? receiptFor(String idempotencyKey) => _receipts[idempotencyKey];

  /// Rebuilds replay protection, terminal receipts, prepared-but-uncertain
  /// effects, and consumed leases from the durable audit journal.
  Future<void> recover() async {
    await _journal.verify();
    _receipts.clear();
    _fingerprints.clear();
    _requests.clear();

    final prepared = <String, _PreparedTool>{};
    final consumedLeaseIds = <String>{};
    final entries = await _journal.readAll();
    for (final entry in entries) {
      if (entry.eventType == 'tool.prepared') {
        final request = ToolRequest.fromJson(
          _objectMap(entry.payload['request'], 'tool.prepared.request'),
        );
        final fingerprint = entry.payload['request_fingerprint'];
        final startedAt = entry.payload['started_at'];
        if (fingerprint is! String ||
            fingerprint != request.fingerprint ||
            startedAt is! String) {
          throw StateError('Malformed tool.prepared entry ${entry.sequence}.');
        }
        prepared[request.idempotencyKey] = _PreparedTool(
          request: request,
          startedAt: DateTime.parse(startedAt).toUtc(),
        );
        final leaseId = entry.payload['lease_id'];
        if (leaseId is String && leaseId.isNotEmpty) {
          consumedLeaseIds.add(leaseId);
        }
        continue;
      }

      if (!<String>{
        'tool.rejected',
        'tool.observed',
        'tool.completed',
        'tool.failed',
        'tool.indeterminate',
        'tool.reconciled',
      }.contains(entry.eventType)) {
        continue;
      }
      final request = ToolRequest.fromJson(
        _objectMap(entry.payload['request'], '${entry.eventType}.request'),
      );
      final receipt = ToolReceipt.fromJson(
        _objectMap(entry.payload['receipt'], '${entry.eventType}.receipt'),
      );
      final fingerprint = entry.payload['request_fingerprint'];
      if (fingerprint is! String || fingerprint != request.fingerprint) {
        throw StateError('Tool terminal fingerprint mismatch at ${entry.sequence}.');
      }
      _cacheReceipt(request: request, receipt: receipt);
    }

    for (final item in prepared.entries) {
      if (_receipts.containsKey(item.key)) {
        continue;
      }
      final value = item.value;
      _cacheReceipt(
        request: value.request,
        receipt: ToolReceipt(
          requestId: value.request.requestId,
          idempotencyKey: value.request.idempotencyKey,
          status: ToolReceiptStatus.indeterminate,
          policyReason: 'recovered_prepared_without_terminal',
          result: <String, Object?>{
            'error': 'authoritative_reconciliation_required',
            'external_id': value.request.idempotencyKey,
          },
          startedAt: value.startedAt,
          completedAt: _clock.now(),
        ),
      );
    }
    _policy.restoreConsumed(consumedLeaseIds);
  }

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
      final receipt = ToolReceipt(
        requestId: request.requestId,
        idempotencyKey: request.idempotencyKey,
        status: ToolReceiptStatus.rejected,
        policyReason: decision.reason,
        result: const <String, Object?>{},
        startedAt: startedAt,
        completedAt: _clock.now(),
      );
      return _recordTerminal(
        eventType: 'tool.rejected',
        request: request,
        receipt: receipt,
      );
    }

    if (request.mutating) {
      await _journal.append('tool.prepared', <String, Object?>{
        'request': request.toJson(),
        'request_fingerprint': request.fingerprint,
        'lease_id': lease?.leaseId,
        'started_at': startedAt.toIso8601String(),
      });
    }
    _policy.consume(lease);

    try {
      final result = await handler(request);
      final receipt = ToolReceipt(
        requestId: request.requestId,
        idempotencyKey: request.idempotencyKey,
        status: ToolReceiptStatus.succeeded,
        policyReason: decision.reason,
        result: Map.unmodifiable(result),
        startedAt: startedAt,
        completedAt: _clock.now(),
      );
      return _recordTerminal(
        eventType: request.mutating ? 'tool.completed' : 'tool.observed',
        request: request,
        receipt: receipt,
      );
    } on IndeterminateToolEffect catch (error) {
      final receipt = ToolReceipt(
        requestId: request.requestId,
        idempotencyKey: request.idempotencyKey,
        status: ToolReceiptStatus.indeterminate,
        policyReason: decision.reason,
        result: <String, Object?>{
          'error': 'tool_effect_indeterminate',
          'external_id': error.externalId,
        },
        startedAt: startedAt,
        completedAt: _clock.now(),
      );
      return _recordTerminal(
        eventType: 'tool.indeterminate',
        request: request,
        receipt: receipt,
      );
    } on Object catch (error) {
      final receipt = ToolReceipt(
        requestId: request.requestId,
        idempotencyKey: request.idempotencyKey,
        status: ToolReceiptStatus.failed,
        policyReason: decision.reason,
        result: <String, Object?>{
          'error': 'tool_execution_failed',
          'error_type': error.runtimeType.toString(),
        },
        startedAt: startedAt,
        completedAt: _clock.now(),
      );
      return _recordTerminal(
        eventType: 'tool.failed',
        request: request,
        receipt: receipt,
      );
    }
  }

  Future<ToolReceipt> reconcile({required String idempotencyKey}) async {
    final prior = _receipts[idempotencyKey];
    final request = _requests[idempotencyKey];
    if (prior == null || request == null) {
      throw StateError('Unknown tool receipt $idempotencyKey.');
    }
    if (prior.status != ToolReceiptStatus.indeterminate) {
      return prior.asReplay();
    }
    final reconciler = _reconcilers[request.action];
    if (reconciler == null) {
      throw StateError('Tool ${request.action} has no reconciler.');
    }
    final externalId =
        prior.result['external_id']?.toString() ?? request.idempotencyKey;
    final result = await reconciler(request, externalId);
    final authoritative = result['authoritative'] == true;
    final receipt = ToolReceipt(
      requestId: request.requestId,
      idempotencyKey: request.idempotencyKey,
      status: authoritative
          ? ToolReceiptStatus.succeeded
          : ToolReceiptStatus.indeterminate,
      policyReason: prior.policyReason,
      result: Map.unmodifiable(result),
      startedAt: prior.startedAt,
      completedAt: _clock.now(),
    );
    return _recordTerminal(
      eventType: 'tool.reconciled',
      request: request,
      receipt: receipt,
    );
  }

  Future<ToolReceipt> _finalizeWithoutEffect({
    required ToolRequest request,
    required DateTime startedAt,
    required ToolReceiptStatus status,
    required String policyReason,
  }) {
    final receipt = ToolReceipt(
      requestId: request.requestId,
      idempotencyKey: request.idempotencyKey,
      status: status,
      policyReason: policyReason,
      result: const <String, Object?>{},
      startedAt: startedAt,
      completedAt: _clock.now(),
    );
    return _recordTerminal(
      eventType: 'tool.rejected',
      request: request,
      receipt: receipt,
    );
  }

  Future<ToolReceipt> _recordTerminal({
    required String eventType,
    required ToolRequest request,
    required ToolReceipt receipt,
  }) async {
    await _journal.append(eventType, <String, Object?>{
      'request': request.toJson(),
      'request_fingerprint': request.fingerprint,
      'receipt': receipt.toJson(),
    });
    return _cacheReceipt(request: request, receipt: receipt);
  }

  ToolReceipt _cacheReceipt({
    required ToolRequest request,
    required ToolReceipt receipt,
  }) {
    _fingerprints[request.idempotencyKey] = request.fingerprint;
    _requests[request.idempotencyKey] = request;
    _receipts[request.idempotencyKey] = receipt;
    return receipt;
  }
}
