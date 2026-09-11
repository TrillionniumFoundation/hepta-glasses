import 'dart:convert';
import 'dart:io';

import 'package:demo_ai_even/runtime/audit_checkpoint_authenticator.dart';
import 'package:demo_ai_even/runtime/audit_journal.dart';
import 'package:flutter_test/flutter_test.dart';

JsonlAuditJournal v3Journal(
  File file, {
  int maximumEntryBytes = 256 * 1024,
  int maximumFileBytes = 64 * 1024 * 1024,
  bool allowLegacyCheckpointMigration = false,
}) =>
    JsonlAuditJournal(
      file,
      checkpointAuthenticator: HmacAuditCheckpointAuthenticator.forTests(),
      maximumEntryBytes: maximumEntryBytes,
      maximumFileBytes: maximumFileBytes,
      allowLegacyCheckpointMigration: allowLegacyCheckpointMigration,
    );

void main() {
  test('v3 checkpoint authenticates exact head length and file metadata',
      () async {
    final directory = await Directory.systemTemp.createTemp(
      'hepta-audit-v3-head-',
    );
    addTearDown(() async => directory.delete(recursive: true));
    final file = File('${directory.path}/audit.jsonl');
    final journal = v3Journal(file);

    await journal.initialize();
    await journal.append('event.one', <String, Object?>{'value': 1});
    await journal.append('event.two', <String, Object?>{'value': 2});

    final checkpoint = jsonDecode(
      await JsonlAuditJournal.checkpointFileFor(file).readAsString(),
    ) as Map<String, dynamic>;
    expect(checkpoint['schema_version'], 3);
    expect(checkpoint['sequence'], 2);
    expect(checkpoint['byte_length'], await file.length());
    expect(checkpoint['modified_micros'], isA<int>());
    expect(checkpoint['changed_micros'], isA<int>());
    expect(checkpoint['authenticator_id'], 'deterministic-test-hmac-sha256-v1');
    expect(checkpoint['mac'], matches(RegExp(r'^[0-9a-f]{64}$')));
  });

  test('normal appends use the bounded authenticated-tail path', () async {
    final directory = await Directory.systemTemp.createTemp(
      'hepta-audit-v3-fast-',
    );
    addTearDown(() async => directory.delete(recursive: true));
    final journal = v3Journal(File('${directory.path}/audit.jsonl'));

    await journal.initialize();
    expect(journal.fullVerificationCount, 1);
    await journal.append('event.one', const <String, Object?>{});
    await journal.append('event.two', const <String, Object?>{});
    await journal.append('event.three', const <String, Object?>{});

    expect(journal.fullVerificationCount, 1);
    expect(journal.fastAppendCount, 3);
    await journal.verify();
    expect(journal.fullVerificationCount, 2);
  });

  test('append is bounded by entry and total journal capacity', () async {
    final directory = await Directory.systemTemp.createTemp(
      'hepta-audit-v3-bounds-',
    );
    addTearDown(() async => directory.delete(recursive: true));
    final file = File('${directory.path}/audit.jsonl');
    final journal = v3Journal(
      file,
      maximumEntryBytes: 1024,
      maximumFileBytes: 2048,
    );
    await journal.initialize();

    await expectLater(
      journal.append('oversized', <String, Object?>{'value': 'x' * 1200}),
      throwsStateError,
    );
    expect(await file.length(), 0);
  });

  test(
    'append validates and advances a valid crash tail beyond the checkpoint',
    () async {
      final directory = await Directory.systemTemp.createTemp(
        'hepta-audit-v3-crash-',
      );
      addTearDown(() async => directory.delete(recursive: true));
      final file = File('${directory.path}/audit.jsonl');
      final first = v3Journal(file);
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

      final recovered = v3Journal(file);
      await recovered.append('event.three', const <String, Object?>{});
      expect(await recovered.readAll(), hasLength(3));
    },
  );

  test(
    'append rejects equal-length middle-record tampering before writing',
    () async {
      final directory = await Directory.systemTemp.createTemp(
        'hepta-audit-v3-middle-tamper-',
      );
      addTearDown(() async => directory.delete(recursive: true));
      final file = File('${directory.path}/audit.jsonl');
      final journal = v3Journal(file);

      await journal.initialize();
      await journal.append('event.one', const <String, Object?>{
        'value': 'AAAAAAAA',
      });
      await journal.append('event.two', const <String, Object?>{
        'value': 'BBBBBBBB',
      });
      await journal.append('event.three', const <String, Object?>{
        'value': 'CCCCCCCC',
      });

      final original = await file.readAsString();
      final checkpointFile = JsonlAuditJournal.checkpointFileFor(file);
      final checkpointBefore = await checkpointFile.readAsString();
      final tampered = original.replaceFirst(
        '"value":"BBBBBBBB"',
        '"value":"XXXXXXXX"',
      );
      expect(tampered, isNot(original));
      expect(utf8.encode(tampered).length, utf8.encode(original).length);
      await file.writeAsString(tampered, flush: true);
      final lengthBeforeAppend = await file.length();

      await expectLater(
        journal.append('event.four', const <String, Object?>{
          'value': 'DDDDDDDD',
        }),
        throwsStateError,
      );

      expect(await file.length(), lengthBeforeAppend);
      expect(await file.readAsString(), tampered);
      expect(await checkpointFile.readAsString(), checkpointBefore);
    },
  );

  test('legacy checkpoint migration requires an explicit constructor flag',
      () async {
    final directory = await Directory.systemTemp.createTemp(
      'hepta-audit-v3-migration-',
    );
    addTearDown(() async => directory.delete(recursive: true));
    final file = File('${directory.path}/audit.jsonl');
    final journal = v3Journal(file);
    await journal.initialize();
    final entry = await journal.append('event.one', const <String, Object?>{});
    await JsonlAuditJournal.checkpointFileFor(file).writeAsString(
      '${jsonEncode(<String, Object?>{
            'schema_version': 2,
            'sequence': 1,
            'hash': entry.hash,
            'byte_length': await file.length(),
          })}\n',
      flush: true,
    );

    await expectLater(v3Journal(file).verify(), throwsStateError);

    final migrated = v3Journal(file, allowLegacyCheckpointMigration: true);
    await migrated.verify();
    final checkpoint = jsonDecode(
      await JsonlAuditJournal.checkpointFileFor(file).readAsString(),
    ) as Map<String, dynamic>;
    expect(checkpoint['schema_version'], 3);
    expect(checkpoint['sequence'], 1);
  });
}
