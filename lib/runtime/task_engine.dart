import 'audit_journal.dart';
import 'canonical_json.dart';
import 'clock.dart';
import 'contracts.dart';

final class TaskEngine {
  TaskEngine({required AuditJournal journal, Clock clock = const SystemClock()})
    : _journal = journal,
      _clock = clock;

  final AuditJournal _journal;
  final Clock _clock;
  final Map<String, TaskRecord> _tasks = <String, TaskRecord>{};
  final Map<String, String> _idempotency = <String, String>{};
  final Map<String, String> _creationFingerprints = <String, String>{};

  static final Map<TaskState, Set<TaskState>> _allowedTransitions =
      <TaskState, Set<TaskState>>{
        TaskState.created: <TaskState>{
          TaskState.validating,
          TaskState.cancelled,
          TaskState.failed,
        },
        TaskState.validating: <TaskState>{
          TaskState.waitingForContext,
          TaskState.waitingForApproval,
          TaskState.running,
          TaskState.cancelled,
          TaskState.failed,
        },
        TaskState.waitingForContext: <TaskState>{
          TaskState.validating,
          TaskState.cancelled,
          TaskState.failed,
        },
        TaskState.waitingForApproval: <TaskState>{
          TaskState.running,
          TaskState.cancelled,
          TaskState.failed,
        },
        TaskState.running: <TaskState>{
          TaskState.waitingForExternal,
          TaskState.reconciling,
          TaskState.succeeded,
          TaskState.failed,
          TaskState.cancelled,
          TaskState.degraded,
        },
        TaskState.waitingForExternal: <TaskState>{
          TaskState.running,
          TaskState.reconciling,
          TaskState.failed,
          TaskState.cancelled,
          TaskState.degraded,
        },
        TaskState.reconciling: <TaskState>{
          TaskState.running,
          TaskState.succeeded,
          TaskState.failed,
          TaskState.cancelled,
          TaskState.degraded,
        },
        TaskState.succeeded: <TaskState>{},
        TaskState.failed: <TaskState>{},
        TaskState.cancelled: <TaskState>{},
        TaskState.degraded: <TaskState>{
          TaskState.reconciling,
          TaskState.failed,
          TaskState.cancelled,
        },
      };

  List<TaskRecord> get tasks => List.unmodifiable(_tasks.values);

  TaskRecord? getTask(String taskId) => _tasks[taskId];

  Future<TaskRecord> createTask({
    required String taskId,
    required String idempotencyKey,
    Map<String, Object?> metadata = const <String, Object?>{},
  }) async {
    if (taskId.trim().isEmpty || idempotencyKey.trim().isEmpty) {
      throw ArgumentError('taskId and idempotencyKey must not be empty');
    }
    final fingerprint = sha256CanonicalJson(<String, Object?>{
      'task_id': taskId,
      'metadata': metadata,
    });
    final existingTaskId = _idempotency[idempotencyKey];
    if (existingTaskId != null) {
      if (_creationFingerprints[idempotencyKey] != fingerprint) {
        throw StateError(
          'Idempotency key was reused with different task data.',
        );
      }
      return _tasks[existingTaskId]!;
    }
    if (_tasks.containsKey(taskId)) {
      throw StateError('Task $taskId already exists.');
    }

    final now = _clock.now();
    final task = TaskRecord(
      taskId: taskId,
      idempotencyKey: idempotencyKey,
      state: TaskState.created,
      createdAt: now,
      updatedAt: now,
      metadata: Map.unmodifiable(metadata),
    );
    await _journal.append('task.created', <String, Object?>{
      'task': task.toJson(),
      'creation_fingerprint': fingerprint,
    });
    _tasks[taskId] = task;
    _idempotency[idempotencyKey] = taskId;
    _creationFingerprints[idempotencyKey] = fingerprint;
    return task;
  }

  Future<TaskRecord> transition(
    String taskId,
    TaskState next, {
    String? reason,
  }) async {
    final current = _tasks[taskId];
    if (current == null) {
      throw StateError('Unknown task $taskId.');
    }
    if (current.state == next) {
      return current;
    }
    final allowed = _allowedTransitions[current.state] ?? const <TaskState>{};
    if (!allowed.contains(next)) {
      throw StateError(
        'Invalid task transition ${current.state.name} -> ${next.name}.',
      );
    }

    final updated = current.transitionTo(
      next,
      _clock.now(),
      transitionReason: reason,
    );
    await _journal.append('task.transition', <String, Object?>{
      'task_id': taskId,
      'from': current.state.name,
      'to': next.name,
      'reason': reason,
      'updated_at': updated.updatedAt.toIso8601String(),
    });
    _tasks[taskId] = updated;
    return updated;
  }

  Future<TaskRecord> cancel(String taskId, {String? reason}) async {
    final current = _tasks[taskId];
    if (current == null) {
      throw StateError('Unknown task $taskId.');
    }
    if (<TaskState>{
      TaskState.succeeded,
      TaskState.failed,
      TaskState.cancelled,
    }.contains(current.state)) {
      return current;
    }
    return transition(
      taskId,
      TaskState.cancelled,
      reason: reason ?? 'cancelled',
    );
  }

  Future<void> recover() async {
    await _journal.verify();
    _tasks.clear();
    _idempotency.clear();
    _creationFingerprints.clear();

    final entries = await _journal.readAll();
    for (final entry in entries) {
      if (entry.eventType == 'task.created') {
        final rawTask = entry.payload['task'];
        if (rawTask is! Map) {
          throw StateError('task.created entry ${entry.sequence} has no task.');
        }
        final task = TaskRecord.fromJson(
          rawTask.map(
            (key, value) => MapEntry(key.toString(), value as Object?),
          ),
        );
        final fingerprint = entry.payload['creation_fingerprint'];
        if (fingerprint is! String) {
          throw StateError(
            'task.created entry ${entry.sequence} has no fingerprint.',
          );
        }
        if (_tasks.containsKey(task.taskId) ||
            _idempotency.containsKey(task.idempotencyKey)) {
          throw StateError('Duplicate task identity in audit journal.');
        }
        _tasks[task.taskId] = task;
        _idempotency[task.idempotencyKey] = task.taskId;
        _creationFingerprints[task.idempotencyKey] = fingerprint;
      } else if (entry.eventType == 'task.transition') {
        final taskId = entry.payload['task_id'];
        final from = entry.payload['from'];
        final to = entry.payload['to'];
        final updatedAt = entry.payload['updated_at'];
        if (taskId is! String ||
            from is! String ||
            to is! String ||
            updatedAt is! String) {
          throw StateError('Malformed task.transition at ${entry.sequence}.');
        }
        final current = _tasks[taskId];
        if (current == null || current.state.name != from) {
          throw StateError('Task transition replay diverged for $taskId.');
        }
        final next = taskStateFromJson(to);
        final allowed =
            _allowedTransitions[current.state] ?? const <TaskState>{};
        if (!allowed.contains(next)) {
          throw StateError('Invalid transition in audit journal for $taskId.');
        }
        _tasks[taskId] = current.transitionTo(
          next,
          DateTime.parse(updatedAt),
          transitionReason: entry.payload['reason'] as String?,
        );
      }
    }
  }
}
