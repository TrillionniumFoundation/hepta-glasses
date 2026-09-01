import 'dart:convert';
import 'dart:io';

import 'package:demo_ai_even/runtime/audit_checkpoint_authenticator.dart';
import 'package:demo_ai_even/runtime/audit_journal.dart';
import 'package:demo_ai_even/runtime/clock.dart';
import 'package:flutter_test/flutter_test.dart';

JsonlAuditJournal journalFor(File file, {Clock? clock}) => JsonlAuditJournal(
      file,
      checkpointAuthenticator: HmacAuditCheckpointAuthenticator.forTests(),
      clock: clock ?? const SystemClock(),
    );

void main() {
  test('in-memory audit journal forms a verifiable hash chain', () async {
    final clock = MutableClock(DateTime.utc(2026, 8, 30));
    final journal = InMemoryAuditJournal(clock: clock);
    await journal.append('task.created', <String, Object?>{'task_id': 't-1'});
    clock.advance(const Duration(seconds: 1));
    await journal.append('task.running', <String, Object?>{'task_id': 't-1'});

    await journal.verify();
    final entries = await journal.readAll();
    expect(entries, hasLength(2));
    expect(entries.last.previousHash, entries.first.hash);
  });

  test('file audit journal serializes concurrent appenders', () async {
    final directory = await Directory.systemTemp.createTemp(
      'hepta-audit-race-',
    );
    addTearDown(() async => directory.delete(recursive: true));
    final journal = journalFor(File('${directory.path}/audit.jsonl'));
    await journal.initialize();

    await Future.wait(
      List<Future<AuditEntry>>.generate(
        32,
        (int index) => journal.append('concurrent.append', <String, Object?>{
          'index': index,
        }),
      ),
    );

    await journal.verify();
    final entries = await journal.readAll();
    expect(entries, hasLength(32));
    expect(
      entries.map((AuditEntry entry) => entry.sequence),
      orderedEquals(List<int>.generate(32, (int index) => index + 1)),
    );
  });

  test('two journal instances share process and operating-system locks', () async {
    final directory = await Directory.systemTemp.createTemp(
      'hepta-audit-cross-instance-',
    );
    addTearDown(() async => directory.delete(recursive: true));
    final file = File('${directory.path}/audit.jsonl');
    final first = journalFor(file);
    final second = journalFor(file);
    await Future.wait(<Future<void>>[first.initialize(), second.initialize()]);

    await Future.wait(
      List<Future<AuditEntry>>.generate(
        64,
        (int index) => (index.isEven ? first : second).append(
          'cross.instance',
          <String, Object?>{'index': index},
        ),
      ),
    );

    await first.verify();
    expect(await second.readAll(), hasLength(64));
  });

  test(
    'stale authenticated checkpoint advances after journal-before-checkpoint crash',
    () async {
      final directory = await Directory.systemTemp.createTemp(
        'hepta-audit-checkpoint-repair-',
      );
      addTearDown(() async => directory.delete(recursive: true));
      final file = File('${directory.path}/audit.jsonl');
      final journal = journalFor(file);
      await journal.initialize();
      final first = await journal.append('tool.prepared', <String, Object?>{
        'request_id': 'r-1',
      });

      final timestamp = DateTime.utc(2026, 8, 31);
      final hash = AuditEntry.calculateHash(
        sequence: 2,
        timestamp: timestamp,
        eventType: 'tool.indeterminate',
        payload: const <String, Object?>{'request_id': 'r-1'},
        previousHash: first.hash,
      );
      final second = AuditEntry(
        sequence: 2,
        timestamp: timestamp,
        eventType: 'tool.indeterminate',
        payload: const <String, Object?>{'request_id': 'r-1'},
        previousHash: first.hash,
        hash: hash,
      );
      await file.writeAsString(
        '${jsonEncode(second.toJson())}\n',
        mode: FileMode.append,
        flush: true,
      );

      final recovered = journalFor(file);
      await recovered.initialize();
      expect(await recovered.readAll(), hasLength(2));
      final checkpoint = jsonDecode(
        await JsonlAuditJournal.checkpointFileFor(file).readAsString(),
      ) as Map<String, dynamic>;
      expect(checkpoint['schema_version'], 3);
      expect(checkpoint['sequence'], 2);
      expect(checkpoint['hash'], hash);
      expect(checkpoint['mac'], matches(RegExp(r'^[0-9a-f]{64}$')));
    },
  );

  test('authenticated checkpoint modification fails closed', () async {
    final directory = await Directory.systemTemp.createTemp(
      'hepta-audit-checkpoint-bad-',
    );
    addTearDown(() async => directory.delete(recursive: true));
    final file = File('${directory.path}/audit.jsonl');
    final journal = journalFor(file);
    await journal.initialize();
    await journal.append('task.created', <String, Object?>{'task_id': 't-1'});
    final checkpointFile = JsonlAuditJournal.checkpointFileFor(file);
    final checkpoint =
        jsonDecode(await checkpointFile.readAsString()) as Map<String, dynamic>;
    checkpoint['sequence'] = 0;
    checkpoint['hash'] = '';
    checkpoint['byte_length'] = 0;
    await checkpointFile.writeAsString('${jsonEncode(checkpoint)}\n', flush: true);

    await expectLater(journalFor(file).verify(), throwsStateError);
  });

  test('missing checkpoint for a non-empty journal fails closed', () async {
    final directory = await Directory.systemTemp.createTemp(
      'hepta-audit-checkpoint-missing-',
    );
    addTearDown(() async => directory.delete(recursive: true));
    final file = File('${directory.path}/audit.jsonl');
    final journal = journalFor(file);
    await journal.initialize();
    await journal.append('task.created', <String, Object?>{'task_id': 't-1'});
    await JsonlAuditJournal.checkpointFileFor(file).delete();

    await expectLater(journalFor(file).verify(), throwsStateError);
  });

  test('torn final record fails closed', () async {
    final directory = await Directory.systemTemp.createTemp(
      'hepta-audit-torn-',
    );
    addTearDown(() async => directory.delete(recursive: true));
    final file = File('${directory.path}/audit.jsonl');
    final journal = journalFor(file);
    await journal.initialize();
    await journal.append('task.created', <String, Object?>{'task_id': 't-1'});
    await file.writeAsString(
      '{"sequence":2',
      mode: FileMode.append,
      flush: true,
    );

    await expectLater(journalFor(file).verify(), throwsStateError);
  });

  test('file audit journal fails closed after record tampering', () async {
    final directory = await Directory.systemTemp.createTemp('hepta-audit-');
    addTearDown(() async => directory.delete(recursive: true));
    final file = File('${directory.path}/audit.jsonl');
    final journal = journalFor(file);
    await journal.initialize();
    await journal.append('tool.prepared', <String, Object?>{
      'request_id': 'r-1',
    });
    await journal.verify();

    final line =
        jsonDecode((await file.readAsLines()).single) as Map<String, dynamic>;
    line['hash'] = '0' * 64;
    await file.writeAsString('${jsonEncode(line)}\n', flush: true);

    await expectLater(journal.verify(), throwsStateError);
  });
}
