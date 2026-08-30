import 'canonical_json.dart';

enum RiskTier { r0, r1, r2, r3, r4 }

enum TaskState {
  created,
  validating,
  waitingForContext,
  waitingForApproval,
  running,
  waitingForExternal,
  reconciling,
  succeeded,
  failed,
  cancelled,
  degraded,
}

enum ToolReceiptStatus { rejected, succeeded, failed, indeterminate }

enum DisplayCardKind {
  status,
  answer,
  list,
  progress,
  confirm,
  warning,
  result,
  error,
}

RiskTier riskTierFromJson(String value) =>
    RiskTier.values.firstWhere((item) => item.name == value);

TaskState taskStateFromJson(String value) =>
    TaskState.values.firstWhere((item) => item.name == value);

ToolReceiptStatus toolReceiptStatusFromJson(String value) =>
    ToolReceiptStatus.values.firstWhere((item) => item.name == value);

DisplayCardKind displayCardKindFromJson(String value) =>
    DisplayCardKind.values.firstWhere((item) => item.name == value);

Map<String, Object?> _stringObjectMap(Object? value) {
  if (value is! Map) {
    throw const FormatException('Expected a JSON object.');
  }
  return value.map(
    (key, item) => MapEntry(key.toString(), item as Object?),
  );
}

final class ToolRequest {
  ToolRequest({
    required this.requestId,
    required this.taskId,
    required this.deviceId,
    required this.action,
    required this.arguments,
    required this.riskTier,
    required this.mutating,
    required this.idempotencyKey,
    required DateTime deadline,
  }) : deadline = deadline.toUtc();

  final String requestId;
  final String taskId;
  final String deviceId;
  final String action;
  final Map<String, Object?> arguments;
  final RiskTier riskTier;
  final bool mutating;
  final String idempotencyKey;
  final DateTime deadline;

  String get fingerprint => sha256CanonicalJson(toJson());

  Map<String, Object?> toJson() => <String, Object?>{
        'request_id': requestId,
        'task_id': taskId,
        'device_id': deviceId,
        'action': action,
        'arguments': arguments,
        'risk_tier': riskTier.name,
        'mutating': mutating,
        'idempotency_key': idempotencyKey,
        'deadline': deadline.toIso8601String(),
      };

  factory ToolRequest.fromJson(Map<String, Object?> json) => ToolRequest(
        requestId: json['request_id']! as String,
        taskId: json['task_id']! as String,
        deviceId: json['device_id']! as String,
        action: json['action']! as String,
        arguments: _stringObjectMap(json['arguments']),
        riskTier: riskTierFromJson(json['risk_tier']! as String),
        mutating: json['mutating']! as bool,
        idempotencyKey: json['idempotency_key']! as String,
        deadline: DateTime.parse(json['deadline']! as String),
      );
}

final class DecisionLease {
  DecisionLease({
    required this.leaseId,
    required this.subject,
    required this.taskId,
    required this.deviceId,
    required Set<String> allowedActions,
    required this.argumentDigest,
    required DateTime expiresAt,
    required this.singleUse,
    required this.policyHash,
  })  : allowedActions = Set.unmodifiable(allowedActions),
        expiresAt = expiresAt.toUtc();

  final String leaseId;
  final String subject;
  final String taskId;
  final String deviceId;
  final Set<String> allowedActions;
  final String argumentDigest;
  final DateTime expiresAt;
  final bool singleUse;
  final String policyHash;

  Map<String, Object?> toJson() => <String, Object?>{
        'lease_id': leaseId,
        'subject': subject,
        'task_id': taskId,
        'device_id': deviceId,
        'allowed_actions': allowedActions.toList()..sort(),
        'argument_digest': argumentDigest,
        'expires_at': expiresAt.toIso8601String(),
        'single_use': singleUse,
        'policy_hash': policyHash,
      };

  factory DecisionLease.fromJson(Map<String, Object?> json) => DecisionLease(
        leaseId: json['lease_id']! as String,
        subject: json['subject']! as String,
        taskId: json['task_id']! as String,
        deviceId: json['device_id']! as String,
        allowedActions: (json['allowed_actions']! as List)
            .map((item) => item.toString())
            .toSet(),
        argumentDigest: json['argument_digest']! as String,
        expiresAt: DateTime.parse(json['expires_at']! as String),
        singleUse: json['single_use']! as bool,
        policyHash: json['policy_hash']! as String,
      );
}

final class ToolSpec {
  const ToolSpec({
    required this.action,
    required this.riskTier,
    required this.mutating,
  });

  final String action;
  final RiskTier riskTier;
  final bool mutating;
}

final class PolicyContext {
  const PolicyContext({
    required this.subject,
    required this.authenticated,
    required this.userPresent,
    required this.biometricVerified,
    required this.policyHash,
  });

  final String subject;
  final bool authenticated;
  final bool userPresent;
  final bool biometricVerified;
  final String policyHash;
}

final class PolicyDecision {
  const PolicyDecision({required this.allowed, required this.reason});

  final bool allowed;
  final String reason;

  Map<String, Object?> toJson() => <String, Object?>{
        'allowed': allowed,
        'reason': reason,
      };
}

final class ToolReceipt {
  ToolReceipt({
    required this.requestId,
    required this.idempotencyKey,
    required this.status,
    required this.policyReason,
    required this.result,
    required DateTime startedAt,
    required DateTime completedAt,
    this.replayed = false,
  })  : startedAt = startedAt.toUtc(),
        completedAt = completedAt.toUtc();

  final String requestId;
  final String idempotencyKey;
  final ToolReceiptStatus status;
  final String policyReason;
  final Map<String, Object?> result;
  final DateTime startedAt;
  final DateTime completedAt;
  final bool replayed;

  ToolReceipt asReplay() => ToolReceipt(
        requestId: requestId,
        idempotencyKey: idempotencyKey,
        status: status,
        policyReason: policyReason,
        result: result,
        startedAt: startedAt,
        completedAt: completedAt,
        replayed: true,
      );

  Map<String, Object?> toJson() => <String, Object?>{
        'request_id': requestId,
        'idempotency_key': idempotencyKey,
        'status': status.name,
        'policy_reason': policyReason,
        'result': result,
        'started_at': startedAt.toIso8601String(),
        'completed_at': completedAt.toIso8601String(),
        'replayed': replayed,
      };

  factory ToolReceipt.fromJson(Map<String, Object?> json) => ToolReceipt(
        requestId: json['request_id']! as String,
        idempotencyKey: json['idempotency_key']! as String,
        status: toolReceiptStatusFromJson(json['status']! as String),
        policyReason: json['policy_reason']! as String,
        result: _stringObjectMap(json['result']),
        startedAt: DateTime.parse(json['started_at']! as String),
        completedAt: DateTime.parse(json['completed_at']! as String),
        replayed: json['replayed'] as bool? ?? false,
      );
}

final class DisplayCard {
  DisplayCard({
    required this.cardId,
    required this.taskId,
    required this.kind,
    required this.title,
    required this.body,
    List<String> actions = const <String>[],
    DateTime? expiresAt,
    this.sensitivity = 'personal',
    this.interruptible = true,
  })  : actions = List.unmodifiable(actions),
        expiresAt = expiresAt?.toUtc();

  final String cardId;
  final String taskId;
  final DisplayCardKind kind;
  final String title;
  final String body;
  final List<String> actions;
  final DateTime? expiresAt;
  final String sensitivity;
  final bool interruptible;

  Map<String, Object?> toJson() => <String, Object?>{
        'card_id': cardId,
        'task_id': taskId,
        'kind': kind.name,
        'title': title,
        'body': body,
        'actions': actions,
        'expires_at': expiresAt?.toIso8601String(),
        'sensitivity': sensitivity,
        'interruptible': interruptible,
      };

  factory DisplayCard.fromJson(Map<String, Object?> json) => DisplayCard(
        cardId: json['card_id']! as String,
        taskId: json['task_id']! as String,
        kind: displayCardKindFromJson(json['kind']! as String),
        title: json['title']! as String,
        body: json['body']! as String,
        actions: (json['actions'] as List? ?? const <Object?>[])
            .map((item) => item.toString())
            .toList(),
        expiresAt: json['expires_at'] == null
            ? null
            : DateTime.parse(json['expires_at']! as String),
        sensitivity: json['sensitivity'] as String? ?? 'personal',
        interruptible: json['interruptible'] as bool? ?? true,
      );
}

final class TaskRecord {
  TaskRecord({
    required this.taskId,
    required this.idempotencyKey,
    required this.state,
    required DateTime createdAt,
    required DateTime updatedAt,
    this.metadata = const <String, Object?>{},
    this.reason,
  })  : createdAt = createdAt.toUtc(),
        updatedAt = updatedAt.toUtc();

  final String taskId;
  final String idempotencyKey;
  final TaskState state;
  final DateTime createdAt;
  final DateTime updatedAt;
  final Map<String, Object?> metadata;
  final String? reason;

  TaskRecord transitionTo(
    TaskState next,
    DateTime at, {
    String? transitionReason,
  }) =>
      TaskRecord(
        taskId: taskId,
        idempotencyKey: idempotencyKey,
        state: next,
        createdAt: createdAt,
        updatedAt: at,
        metadata: metadata,
        reason: transitionReason,
      );

  Map<String, Object?> toJson() => <String, Object?>{
        'task_id': taskId,
        'idempotency_key': idempotencyKey,
        'state': state.name,
        'created_at': createdAt.toIso8601String(),
        'updated_at': updatedAt.toIso8601String(),
        'metadata': metadata,
        'reason': reason,
      };

  factory TaskRecord.fromJson(Map<String, Object?> json) => TaskRecord(
        taskId: json['task_id']! as String,
        idempotencyKey: json['idempotency_key']! as String,
        state: taskStateFromJson(json['state']! as String),
        createdAt: DateTime.parse(json['created_at']! as String),
        updatedAt: DateTime.parse(json['updated_at']! as String),
        metadata: _stringObjectMap(json['metadata']),
        reason: json['reason'] as String?,
      );
}
