import 'dart:convert';
import 'dart:io';

import 'package:demo_ai_even/runtime/audit_journal.dart';
import 'package:demo_ai_even/runtime/clock.dart';
import 'package:flutter_test/flutter_test.dart';

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
}
