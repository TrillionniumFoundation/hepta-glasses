import 'dart:convert';
import 'dart:io';
import 'dart:isolate';

import 'package:demo_ai_even/runtime/audit_journal.dart';
import 'package:demo_ai_even/runtime/clock.dart';
import 'package:flutter_test/flutter_test.dart';

Future<void> _appendFromIsolate(
  String path,
  int firstIndex,
  int count,
) =>
    Isolate.run(() async {
      final journal = JsonlAuditJournal(File(path));
      await journal.initialize();
      for (var offset = 0; offset < count; offset++) {
        await journal.append(
          'isolate.append',
          <String, Object?>{'index': firstIndex + offset},
        );
      }
    });

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
    final directory =
        await Directory.systemTemp.createTemp('hepta-audit-race-');
    addTearDown(() async {
      await directory.delete(recursive: true);
    });
    final journal = JsonlAuditJournal(
      File('${directory.path}/audit.jsonl'),
    );
    await journal.initialize();

    await Future.wait(
      List<Future<AuditEntry>>.generate(
        32,
        (int index) => journal.append(
          'concurrent.append',
          <String, Object?>{'index': index},
        ),
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

  test('file audit journal serializes independent instances', () async {
    final directory =
        await Directory.systemTemp.createTemp('hepta-audit-multi-instance-');
    addTearDown(() async {
      await directory.delete(recursive: true);
    });
    final file = File('${directory.path}/audit.jsonl');
    final first = JsonlAuditJournal(file);
    final second = JsonlAuditJournal(file);
    await Future.wait(<Future<void>>[
      first.initialize(),
      second.initialize(),
    ]);

    await Future.wait(<Future<AuditEntry>>[
      for (var index = 0; index < 32; index++)
        (index.isEven ? first : second).append(
          'multi-instance.append',
          <String, Object?>{'index': index},
        ),
    ]);

    final reader = JsonlAuditJournal(file);
    await reader.initialize();
    final entries = await reader.readAll();
    expect(entries, hasLength(32));
    expect(
      entries.map((AuditEntry entry) => entry.sequence),
      orderedEquals(List<int>.generate(32, (int index) => index + 1)),
    );
  });

  test('file audit journal serializes writers from separate isolates',
      () async {
    final directory =
        await Directory.systemTemp.createTemp('hepta-audit-isolates-');
    addTearDown(() async {
      await directory.delete(recursive: true);
    });
    final path = '${directory.path}/audit.jsonl';

    await Future.wait(<Future<void>>[
      _appendFromIsolate(path, 0, 12),
      _appendFromIsolate(path, 12, 12),
    ]);

    final journal = JsonlAuditJournal(File(path));
    await journal.initialize();
    final entries = await journal.readAll();
    expect(entries, hasLength(24));
    expect(
      entries.map((AuditEntry entry) => entry.sequence),
      orderedEquals(List<int>.generate(24, (int index) => index + 1)),
    );
    expect(
      entries.map((AuditEntry entry) => entry.payload['index']).toSet(),
      equals(<Object?>{for (var index = 0; index < 24; index++) index}),
    );
  });

  test('file audit journal fails closed after tampering', () async {
    final directory = await Directory.systemTemp.createTemp('hepta-audit-');
    addTearDown(() async {
      await directory.delete(recursive: true);
    });
    final file = File('${directory.path}/audit.jsonl');
    final journal = JsonlAuditJournal(file);
    await journal.initialize();
    await journal
        .append('tool.prepared', <String, Object?>{'request_id': 'r-1'});
    await journal.verify();

    final line =
        jsonDecode((await file.readAsLines()).single) as Map<String, dynamic>;
    line['hash'] = 'tampered';
    await file.writeAsString('${jsonEncode(line)}\n', flush: true);

    await expectLater(journal.verify(), throwsStateError);
  });

  test('file audit journal fails closed on a torn final record', () async {
    final directory =
        await Directory.systemTemp.createTemp('hepta-audit-torn-');
    addTearDown(() async {
      await directory.delete(recursive: true);
    });
    final file = File('${directory.path}/audit.jsonl');
    final journal = JsonlAuditJournal(file);
    await journal.initialize();
    await journal.append('task.created', <String, Object?>{'task_id': 't-1'});
    await file.writeAsString(
      '{"sequence":2',
      mode: FileMode.append,
      flush: true,
    );

    await expectLater(
      JsonlAuditJournal(file).initialize(),
      throwsStateError,
    );
  });

  test('file audit journal enforces entry and file bounds', () async {
    final directory =
        await Directory.systemTemp.createTemp('hepta-audit-bounds-');
    addTearDown(() async {
      await directory.delete(recursive: true);
    });

    final entryBounded = JsonlAuditJournal(
      File('${directory.path}/entry-bounded.jsonl'),
      maxEntries: 1,
    );
    await entryBounded.initialize();
    await entryBounded.append('first', const <String, Object?>{});
    await expectLater(
      entryBounded.append('second', const <String, Object?>{}),
      throwsStateError,
    );

    final byteBounded = JsonlAuditJournal(
      File('${directory.path}/byte-bounded.jsonl'),
      maxBytes: 512,
      maxEntryBytes: 256,
    );
    await byteBounded.initialize();
    await expectLater(
      byteBounded.append(
        'oversized',
        <String, Object?>{'value': List<String>.filled(300, 'x').join()},
      ),
      throwsStateError,
    );
  });
}
