import 'dart:convert';
import 'dart:io';

import 'package:demo_ai_even/runtime/audit_journal.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('v2 checkpoint binds the exact journal byte length', () async {
    final directory =
        await Directory.systemTemp.createTemp('hepta-audit-v2-head-');
    addTearDown(() async => directory.delete(recursive: true));
    final file = File('${directory.path}/audit.jsonl');
    final journal = JsonlAuditJournal(file);

    await journal.initialize();
    await journal.append('event.one', <String, Object?>{'value': 1});
    await journal.append('event.two', <String, Object?>{'value': 2});

    final checkpoint = jsonDecode(
      await JsonlAuditJournal.checkpointFileFor(file).readAsString(),
    ) as Map<String, dynamic>;
    expect(checkpoint['schema_version'], 2);
    expect(checkpoint['sequence'], 2);
    expect(checkpoint['byte_length'], await file.length());
  });

  test('append is bounded by entry and total journal capacity', () async {
    final directory =
        await Directory.systemTemp.createTemp('hepta-audit-v2-bounds-');
    addTearDown(() async => directory.delete(recursive: true));
    final file = File('${directory.path}/audit.jsonl');
    final journal = JsonlAuditJournal(
      file,
      maximumEntryBytes: 1024,
      maximumFileBytes: 2048,
    );
    await journal.initialize();

    await expectLater(
      journal.append(
        'oversized',
        <String, Object?>{'value': 'x' * 1200},
      ),
      throwsStateError,
    );
    expect(await file.length(), 0);
  });

  test('append repairs a valid journal tail written before checkpoint update',
      () async {
    final directory =
        await Directory.systemTemp.createTemp('hepta-audit-v2-crash-');
    addTearDown(() async => directory.delete(recursive: true));
    final file = File('${directory.path}/audit.jsonl');
    final first = JsonlAuditJournal(file);
    await first.initialize();
    final entry = await first.append('event.one', const <String, Object?>{});

    final timestamp = DateTime.utc(2026, 8, 31, 12);
    final hash = AuditEntry.calculateHash(
      sequence: 2,
      timestamp: timestamp,
      eventType: 'event.two',
      payload: const <String, Object?>{},
      previousHash: entry.hash,
    );
    final second = AuditEntry(
      sequence: 2,
      timestamp: timestamp,
      eventType: 'event.two',
      payload: const <String, Object?>{},
      previousHash: entry.hash,
      hash: hash,
    );
    await file.writeAsString(
      '${jsonEncode(second.toJson())}\n',
      mode: FileMode.append,
      flush: true,
    );

    final recovered = JsonlAuditJournal(file);
    await recovered.append('event.three', const <String, Object?>{});
    expect(await recovered.readAll(), hasLength(3));
  });
}
