import 'dart:async';

import 'audit_journal.dart';
import 'canonical_json.dart';
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

typedef ToolRecoveryReconciler = Future<Map<String, Object?>> Function(
  ToolAuditEnvelope request,
  String externalId,
);

final class IndeterminateToolEffect implements Exception {
  const IndeterminateToolEffect(this.externalId);

  final String externalId;

  @override
  String toString() => 'IndeterminateToolEffect($externalId)';
}

/// Metadata-only request representation. It is sufficient for replay conflict
/// detection and recovery routing without persisting prompts, notification
/// bodies, display text, locations, contacts, or other sensitive arguments.
final class ToolAuditEnvelope {
  ToolAuditEnvelope({
    required this.requestId,
    required this.taskId,
    required this.deviceId,
    required this.action,
    required this.riskTier,
    required this.mutating,
    required this.idempotencyKey,
    required DateTime deadline,
    required this.origin,
    required this.argumentDigest,
    required this.requestFingerprint,
  }) : deadline = deadline.toUtc();

  factory ToolAuditEnvelope.fromRequest(ToolRequest request) =>
      ToolAuditEnvelope(
        requestId: request.requestId,
        taskId: request.taskId,
        deviceId: request.deviceId,
        action: request.action,
        riskTier: request.riskTier,
        mutating: request.mutating,
        idempotencyKey: request.idempotencyKey,
        deadline: request.deadline,
        origin: request.origin,
        argumentDigest: request.argumentDigest,
        requestFingerprint: request.fingerprint,
      );

  final String requestId;
  final String taskId;
  final String deviceId;
  final String action;
  final RiskTier riskTier;
  final bool mutating;
  final String idempotencyKey;
  final DateTime deadline;
  final TrustClass origin;
  final String argumentDigest;
  final String requestFingerprint;

  Map<String, Object?> toJson() => <String, Object?>{
        'request_id': requestId,
        'task_id': taskId,
        'device_id': deviceId,
        'action': action,
        'risk_tier': riskTier.name,
        'mutating': mutating,
        'idempotency_key': idempotencyKey,
        'deadline': deadline.toIso8601String(),
        'origin': origin.name,
        'argument_digest': argumentDigest,
        'request_fingerprint': requestFingerprint,
      };

  factory ToolAuditEnvelope.fromJson(Map<String, Object?> json) =>
      ToolAuditEnvelope(
        requestId: json['request_id']! as String,
        taskId: json['task_id']! as String,
        deviceId: json['device_id']! as String,
        action: json['action']! as String,
        riskTier: riskTierFromJson(json['risk_tier']! as String),
        mutating: json['mutating']! as bool,
        idempotencyKey: json['idempotency_key']! as String,
        deadline: DateTime.parse(json['deadline']! as String),
        origin: trustClassFromJson(json['origin'] as String? ?? 'user'),
        argumentDigest: json['argument_digest']! as String,
        requestFingerprint: json['request_fingerprint']! as String,
      );
}

final class _PreparedTool {
  const _PreparedTool({required this.envelope, required this.startedAt});

  final ToolAuditEnvelope envelope;
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

bool _isSha256(String value) =>
    value.length == 64 &&
    value.toLowerCase().runes.every(
          (character) =>
              (character >= 48 && character <= 57) ||
              (character >= 97 && character <= 102),
        );

Map<String, Object?> _receiptAuditJson(ToolReceipt receipt) {
  final externalId = receipt.result['external_id'];
  return <String, Object?>{
    'request_id': receipt.requestId,
    'idempotency_key': receipt.idempotencyKey,
    'status': receipt.status.name,
    'policy_reason': receipt.policyReason,
    'started_at': receipt.startedAt.toIso8601String(),
    'completed_at': receipt.completedAt.toIso8601String(),
    'result_digest': sha256CanonicalJson(receipt.result),
    if (externalId is String && externalId.isNotEmpty)
      'external_id': externalId,
  };
}

ToolReceipt _receiptFromAuditJson(Map<String, Object?> json) {
  // Backward compatibility for journals produced before metadata-only audit.
  if (json['result'] is Map) {
    return ToolReceipt.fromJson(json);
  }
  final resultDigest = json['result_digest'];
  if (resultDigest is! String || !_isSha256(resultDigest)) {
    throw StateError('Recovered tool receipt has an invalid result digest.');
  }
  final externalId = json['external_id'];
  return ToolReceipt(
    requestId: json['request_id']! as String,
    idempotencyKey: json['idempotency_key']! as String,
    status: toolReceiptStatusFromJson(json['status']! as String),
    policyReason: json['policy_reason']! as String,
    result: <String, Object?>{
      'recovered': true,
      'result_digest': resultDigest,
      if (externalId is String && externalId.isNotEmpty)
        'external_id': externalId,
    },
    startedAt: DateTime.parse(json['started_at']! as String),
    completedAt: DateTime.parse(json['completed_at']! as String),
    replayed: false,
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
  final Map<String, ToolRecoveryReconciler> _recoveryReconcilers =
      <String, ToolRecoveryReconciler>{};
  final Map<String, ToolReceipt> _receipts = <String, ToolReceipt>{};
  final Map<String, String> _fingerprints = <String, String>{};
  final Map<String, ToolRequest> _requests = <String, ToolRequest>{};
  final Map<String, ToolAuditEnvelope> _envelopes =
      <String, ToolAuditEnvelope>{};
  final Map<String, Future<ToolReceipt>> _inFlight =
      <String, Future<ToolReceipt>>{};
  final Map<String, String> _inFlightFingerprints = <String, String>{};

  void register(
    ToolSpec spec,
    ToolHandler handler, {
    ToolReconciler? reconciler,
    ToolRecoveryReconciler? recoveryReconciler,
  }) {
    if (_specs.containsKey(spec.action)) {
      throw StateError('Tool ${spec.action} is already registered.');
    }
    _specs[spec.action] = spec;
    _handlers[spec.action] = handler;
    if (reconciler != null) {
      _reconcilers[spec.action] = reconciler;
    }
    if (recoveryReconciler != null) {
      _recoveryReconcilers[spec.action] = recoveryReconciler;
    }
  }

  List<ToolSpec> get tools => List.unmodifiable(_specs.values);

  ToolReceipt? receiptFor(String idempotencyKey) => _receipts[idempotencyKey];

  /// Rebuilds replay protection, terminal receipts, prepared-but-uncertain
  /// effects, and consumed leases from the durable metadata-only journal.
  Future<void> recover() async {
    if (_inFlight.isNotEmpty) {
      throw StateError(
          'Cannot recover ToolGateway while effects are in flight.');
    }
    await _journal.verify();
    _receipts.clear();
    _fingerprints.clear();
    _requests.clear();
    _envelopes.clear();

    final prepared = <String, _PreparedTool>{};
    final consumedLeaseIds = <String>{};
    final entries = await _journal.readAll();
    for (final entry in entries) {
      if (entry.eventType == 'tool.prepared') {
        final envelope = _envelopeFromPayload(
          entry.payload,
          'tool.prepared',
        );
        final startedAt = entry.payload['started_at'];
        if (startedAt is! String) {
          throw StateError('Malformed tool.prepared entry ${entry.sequence}.');
        }
        prepared[envelope.idempotencyKey] = _PreparedTool(
          envelope: envelope,
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
      final envelope = _envelopeFromPayload(
        entry.payload,
        entry.eventType,
      );
      final receipt = _receiptFromAuditJson(
        _objectMap(entry.payload['receipt'], '${entry.eventType}.receipt'),
      );
      if (receipt.idempotencyKey != envelope.idempotencyKey ||
          receipt.requestId != envelope.requestId) {
        throw StateError(
            'Tool terminal identity mismatch at ${entry.sequence}.');
      }
      _cacheRecovered(envelope: envelope, receipt: receipt);
    }

    for (final item in prepared.entries) {
      if (_receipts.containsKey(item.key)) {
        continue;
      }
      final value = item.value;
      _cacheRecovered(
        envelope: value.envelope,
        receipt: ToolReceipt(
          requestId: value.envelope.requestId,
          idempotencyKey: value.envelope.idempotencyKey,
          status: ToolReceiptStatus.indeterminate,
          policyReason: 'recovered_prepared_without_terminal',
          result: <String, Object?>{
            'error': 'authoritative_reconciliation_required',
            'external_id': value.envelope.idempotencyKey,
          },
          startedAt: value.startedAt,
          completedAt: _clock.now(),
        ),
      );
    }
    _policy.restoreConsumed(consumedLeaseIds);
  }

  ToolAuditEnvelope _envelopeFromPayload(
    Map<String, Object?> payload,
    String label,
  ) {
    final rawEnvelope = payload['request_envelope'];
    if (rawEnvelope != null) {
      final envelope = ToolAuditEnvelope.fromJson(
        _objectMap(rawEnvelope, '$label.request_envelope'),
      );
      if (!_isSha256(envelope.argumentDigest) ||
          !_isSha256(envelope.requestFingerprint)) {
        throw StateError('$label contains an invalid digest.');
      }
      return envelope;
    }

    // Backward compatibility: read legacy full-request records, but never emit
    // another one. Existing local journals therefore migrate on the next write.
    final request = ToolRequest.fromJson(
      _objectMap(payload['request'], '$label.request'),
    );
    final fingerprint = payload['request_fingerprint'];
    if (fingerprint is! String || fingerprint != request.fingerprint) {
      throw StateError('$label request fingerprint mismatch.');
    }
    return ToolAuditEnvelope.fromRequest(request);
  }

  Future<ToolReceipt> execute({
    required ToolRequest request,
    required PolicyContext context,
    DecisionLease? lease,
  }) {
    final existing = _receipts[request.idempotencyKey];
    if (existing != null) {
      if (_fingerprints[request.idempotencyKey] != request.fingerprint) {
        throw StateError(
          'Idempotency key was reused with different tool request data.',
        );
      }
      return Future<ToolReceipt>.value(existing.asReplay());
    }

    final active = _inFlight[request.idempotencyKey];
    if (active != null) {
      if (_inFlightFingerprints[request.idempotencyKey] !=
          request.fingerprint) {
        throw StateError(
          'Idempotency key is in flight with different tool request data.',
        );
      }
      return active.then((ToolReceipt receipt) => receipt.asReplay());
    }

    final operation = _executeOnce(
      request: request,
      context: context,
      lease: lease,
    );
    _inFlight[request.idempotencyKey] = operation;
    _inFlightFingerprints[request.idempotencyKey] = request.fingerprint;
    return operation.whenComplete(() {
      if (identical(_inFlight[request.idempotencyKey], operation)) {
        _inFlight.remove(request.idempotencyKey);
        _inFlightFingerprints.remove(request.idempotencyKey);
      }
    });
  }

  Future<ToolReceipt> _executeOnce({
    required ToolRequest request,
    required PolicyContext context,
    DecisionLease? lease,
  }) async {
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
    if (decision.allowed) {
      // Reserve single-use authority before the first asynchronous boundary.
      // Otherwise a second idempotency key can evaluate the same lease while
      // this request is waiting for its decision/prepared journal writes.
      _policy.consume(lease);
    }
    await _journal.append('tool.decision', <String, Object?>{
      'request_id': request.requestId,
      'task_id': request.taskId,
      'action': request.action,
      'idempotency_key': request.idempotencyKey,
      'request_fingerprint': request.fingerprint,
      'argument_digest': request.argumentDigest,
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
        'request_envelope': ToolAuditEnvelope.fromRequest(request).toJson(),
        'lease_id': lease?.leaseId,
        'started_at': startedAt.toIso8601String(),
      });
    }

    try {
      final remaining = request.deadline.difference(_clock.now());
      if (remaining <= Duration.zero) {
        throw IndeterminateToolEffect(
          '${request.action}:${request.idempotencyKey}',
        );
      }
      final result = await handler(request).timeout(
        remaining,
        onTimeout: () => throw IndeterminateToolEffect(
          '${request.action}:${request.idempotencyKey}',
        ),
      );
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
    final envelope = _envelopes[idempotencyKey];
    if (prior == null || envelope == null) {
      throw StateError('Unknown tool receipt $idempotencyKey.');
    }
    if (prior.status != ToolReceiptStatus.indeterminate) {
      return prior.asReplay();
    }
    final externalId =
        prior.result['external_id']?.toString() ?? envelope.idempotencyKey;
    final liveRequest = _requests[idempotencyKey];
    Map<String, Object?> result;
    if (liveRequest != null && _reconcilers[envelope.action] != null) {
      result = await _reconcilers[envelope.action]!(liveRequest, externalId);
    } else {
      final recoveryReconciler = _recoveryReconcilers[envelope.action];
      if (recoveryReconciler == null) {
        throw StateError(
          'Tool ${envelope.action} has no recovery-safe reconciler.',
        );
      }
      result = await recoveryReconciler(envelope, externalId);
    }
    final authoritative = result['authoritative'] == true;
    final receipt = ToolReceipt(
      requestId: envelope.requestId,
      idempotencyKey: envelope.idempotencyKey,
      status: authoritative
          ? ToolReceiptStatus.succeeded
          : ToolReceiptStatus.indeterminate,
      policyReason: prior.policyReason,
      result: Map.unmodifiable(result),
      startedAt: prior.startedAt,
      completedAt: _clock.now(),
    );
    if (liveRequest != null) {
      return _recordTerminal(
        eventType: 'tool.reconciled',
        request: liveRequest,
        receipt: receipt,
      );
    }
    await _journal.append('tool.reconciled', <String, Object?>{
      'request_envelope': envelope.toJson(),
      'receipt': _receiptAuditJson(receipt),
    });
    return _cacheRecovered(envelope: envelope, receipt: receipt);
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
    final envelope = ToolAuditEnvelope.fromRequest(request);
    try {
      await _journal.append(eventType, <String, Object?>{
        'request_envelope': envelope.toJson(),
        'receipt': _receiptAuditJson(receipt),
      });
    } on Object catch (error) {
      if (!request.mutating) {
        rethrow;
      }
      final uncertain = ToolReceipt(
        requestId: request.requestId,
        idempotencyKey: request.idempotencyKey,
        status: ToolReceiptStatus.indeterminate,
        policyReason: 'terminal_journal_write_failed',
        result: <String, Object?>{
          'error': 'terminal_journal_write_failed',
          'error_type': error.runtimeType.toString(),
          'external_id': '${request.action}:${request.idempotencyKey}',
        },
        startedAt: receipt.startedAt,
        completedAt: _clock.now(),
      );
      return _cacheLive(
        request: request,
        envelope: envelope,
        receipt: uncertain,
      );
    }
    return _cacheLive(
      request: request,
      envelope: envelope,
      receipt: receipt,
    );
  }

  ToolReceipt _cacheLive({
    required ToolRequest request,
    required ToolAuditEnvelope envelope,
    required ToolReceipt receipt,
  }) {
    _fingerprints[request.idempotencyKey] = request.fingerprint;
    _requests[request.idempotencyKey] = request;
    _envelopes[request.idempotencyKey] = envelope;
    _receipts[request.idempotencyKey] = receipt;
    return receipt;
  }

  ToolReceipt _cacheRecovered({
    required ToolAuditEnvelope envelope,
    required ToolReceipt receipt,
  }) {
    _fingerprints[envelope.idempotencyKey] = envelope.requestFingerprint;
    _envelopes[envelope.idempotencyKey] = envelope;
    _receipts[envelope.idempotencyKey] = receipt;
    return receipt;
  }
}
