import 'package:demo_ai_even/runtime/audit_journal.dart';
import 'package:demo_ai_even/runtime/clock.dart';
import 'package:demo_ai_even/runtime/contracts.dart';
import 'package:demo_ai_even/runtime/task_engine.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('task lifecycle is durable and recoverable', () async {
    final clock = MutableClock(DateTime.utc(2026, 8, 30));
    final journal = InMemoryAuditJournal(clock: clock);
    final engine = TaskEngine(journal: journal, clock: clock);

    await engine.createTask(
      taskId: 'task-1',
      idempotencyKey: 'create-1',
      metadata: const <String, Object?>{'kind': 'read-only'},
    );
    await engine.transition('task-1', TaskState.validating);
    await engine.transition('task-1', TaskState.running);
    await engine.transition('task-1', TaskState.succeeded);

    final recovered = TaskEngine(journal: journal, clock: clock);
    await recovered.recover();
    expect(recovered.getTask('task-1')?.state, TaskState.succeeded);
  });

  test('task creation idempotency rejects conflicting replay', () async {
    final journal = InMemoryAuditJournal();
    final engine = TaskEngine(journal: journal);
    await engine.createTask(taskId: 'task-1', idempotencyKey: 'same');

    await expectLater(
      engine.createTask(taskId: 'task-2', idempotencyKey: 'same'),
      throwsStateError,
    );
  });

  test('terminal task cannot be restarted', () async {
    final journal = InMemoryAuditJournal();
    final engine = TaskEngine(journal: journal);
    await engine.createTask(taskId: 'task-1', idempotencyKey: 'create-1');
    await engine.transition('task-1', TaskState.failed);

    await expectLater(
      engine.transition('task-1', TaskState.running),
      throwsStateError,
    );
  });
}
