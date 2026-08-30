import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'canonical_json.dart';
import 'clock.dart';

final class AuditEntry {
  AuditEntry({
    required this.sequence,
    required DateTime timestamp,
    required this.eventType,
    required this.payload,
    required this.previousHash,
    required this.hash,
  }) : timestamp = timestamp.toUtc();

  final int sequence;
  final DateTime timestamp;
  final String eventType;
  final Map<String, Object?> payload;
  final String previousHash;
  final String hash;

  static String calculateHash({
    required int sequence,
    required DateTime timestamp,
    required String eventType,
    required Map<String, Object?> payload,
    required String previousHash,
  }) =>
      sha256CanonicalJson(<String, Object?>{
        'sequence': sequence,
        'timestamp': timestamp.toUtc().toIso8601String(),
        'event_type': eventType,
        'payload': payload,
        'previous_hash': previousHash,
      });

  Map<String, Object?> toJson() => <String, Object?>{
        'sequence': sequence,
        'timestamp': timestamp.toIso8601String(),
        'event_type': eventType,
        'payload': payload,
        'previous_hash': previousHash,
        'hash': hash,
      };

  factory AuditEntry.fromJson(Map<String, Object?> json) {
    final rawPayload = json['payload'];
    if (rawPayload is! Map) {
      throw const FormatException('Audit payload must be an object.');
    }
    final sequence = json['sequence'];
    final timestamp = json['timestamp'];
    final eventType = json['event_type'];
    final previousHash = json['previous_hash'];
    final hash = json['hash'];
    if (sequence is! int ||
        timestamp is! String ||
        eventType is! String ||
        previousHash is! String ||
        hash is! String) {
      throw const FormatException('Audit entry has invalid field types.');
    }
    return AuditEntry(
      sequence: sequence,
      timestamp: DateTime.parse(timestamp),
      eventType: eventType,
      payload: rawPayload.map(
        (key, value) => MapEntry(key.toString(), value as Object?),
      ),
      previousHash: previousHash,
      hash: hash,
    );
  }
}

abstract interface class AuditJournal {
  Future<AuditEntry> append(
    String eventType,
    Map<String, Object?> payload,
  );

  Future<List<AuditEntry>> readAll();

  Future<void> verify();
}

mixin _AuditVerification {
  Future<void> verifyEntries(List<AuditEntry> entries) async {
    var previousHash = '';
    for (var index = 0; index < entries.length; index++) {
      final entry = entries[index];
      if (entry.sequence != index + 1) {
        throw StateError(
          'Audit sequence mismatch at ${entry.sequence}; expected ${index + 1}.',
        );
      }
      if (entry.previousHash != previousHash) {
        throw StateError('Audit previous-hash mismatch at ${entry.sequence}.');
      }
      final calculated = AuditEntry.calculateHash(
        sequence: entry.sequence,
        timestamp: entry.timestamp,
        eventType: entry.eventType,
        payload: entry.payload,
        previousHash: entry.previousHash,
      );
      if (calculated != entry.hash) {
        throw StateError('Audit hash mismatch at ${entry.sequence}.');
      }
      previousHash = entry.hash;
    }
  }
}

final class InMemoryAuditJournal
    with _AuditVerification
    implements AuditJournal {
  InMemoryAuditJournal({Clock clock = const SystemClock()}) : _clock = clock;

  final Clock _clock;
  final List<AuditEntry> _entries = <AuditEntry>[];

  @override
  Future<AuditEntry> append(
    String eventType,
    Map<String, Object?> payload,
  ) async {
    if (eventType.trim().isEmpty) {
      throw ArgumentError.value(eventType, 'eventType', 'must not be empty');
    }
    final sequence = _entries.length + 1;
    final previousHash = _entries.isEmpty ? '' : _entries.last.hash;
    final timestamp = _clock.now().toUtc();
    final hash = AuditEntry.calculateHash(
      sequence: sequence,
      timestamp: timestamp,
      eventType: eventType,
      payload: payload,
      previousHash: previousHash,
    );
    final entry = AuditEntry(
      sequence: sequence,
      timestamp: timestamp,
      eventType: eventType,
      payload: Map.unmodifiable(payload),
      previousHash: previousHash,
      hash: hash,
    );
    _entries.add(entry);
    return entry;
  }

  @override
  Future<List<AuditEntry>> readAll() async => List.unmodifiable(_entries);

  @override
  Future<void> verify() async => verifyEntries(_entries);
}

final class _AuditHead {
  const _AuditHead(this.sequence, this.hash);

  final int sequence;
  final String hash;

  Map<String, Object?> toJson() => <String, Object?>{
        'schema_version': 1,
        'sequence': sequence,
        'hash': hash,
      };
}

/// A process-safe JSONL journal.
///
/// Every operation takes an OS advisory lock on a stable sibling lock file.
/// The journal entry is flushed before an atomically replaced head checkpoint,
/// so process death between the two writes is repaired without replaying a
/// physical effect. A checkpoint that is ahead of, or inconsistent with, the
/// hash chain fails closed.
final class JsonlAuditJournal with _AuditVerification implements AuditJournal {
  JsonlAuditJournal(this.file, {Clock clock = const SystemClock()})
      : _clock = clock;

  static const String contractVersion = 'file-lock-checkpoint-v1';

  final File file;
  final Clock _clock;
  Future<void> _tail = Future<void>.value();

  static File lockFileFor(File file) => File('${file.path}.lock');
  static File checkpointFileFor(File file) => File('${file.path}.head.json');

  Future<T> _exclusive<T>(Future<T> Function() operation) {
    final completer = Completer<T>();
    _tail = _tail.then((_) async {
      try {
        completer.complete(await _withFileLock(operation));
      } on Object catch (error, stackTrace) {
        completer.completeError(error, stackTrace);
      }
    });
    return completer.future;
  }

  Future<T> _withFileLock<T>(Future<T> Function() operation) async {
    final lockFile = lockFileFor(file);
    await lockFile.parent.create(recursive: true);
    if (!await lockFile.exists()) {
      await lockFile.create(recursive: true);
    }
    final handle = await lockFile.open(mode: FileMode.append);
    try {
      await handle.lock(FileLock.exclusive);
      return await operation();
    } finally {
      try {
        await handle.unlock();
      } finally {
        await handle.close();
      }
    }
  }

  Future<void> initialize() => _exclusive(() async {
        await _ensureDataFileUnlocked();
        final entries = await _readAndVerifyUnlocked();
        await _verifyOrRepairCheckpointUnlocked(entries);
      });

  @override
  Future<AuditEntry> append(
    String eventType,
    Map<String, Object?> payload,
  ) =>
      _exclusive(() async {
        if (eventType.trim().isEmpty) {
          throw ArgumentError.value(
            eventType,
            'eventType',
            'must not be empty',
          );
        }
        await _ensureDataFileUnlocked();
        final entries = await _readAndVerifyUnlocked();
        await _verifyOrRepairCheckpointUnlocked(entries);

        final sequence = entries.length + 1;
        final previousHash = entries.isEmpty ? '' : entries.last.hash;
        final timestamp = _clock.now().toUtc();
        final hash = AuditEntry.calculateHash(
          sequence: sequence,
          timestamp: timestamp,
          eventType: eventType,
          payload: payload,
          previousHash: previousHash,
        );
        final entry = AuditEntry(
          sequence: sequence,
          timestamp: timestamp,
          eventType: eventType,
          payload: Map.unmodifiable(payload),
          previousHash: previousHash,
          hash: hash,
        );

        final handle = await file.open(mode: FileMode.append);
        try {
          await handle.writeString('${canonicalJson(entry.toJson())}\n');
          await handle.flush();
        } finally {
          await handle.close();
        }
        await _writeCheckpointUnlocked(_AuditHead(sequence, hash));
        return entry;
      });

  @override
  Future<List<AuditEntry>> readAll() => _exclusive(() async {
        await _ensureDataFileUnlocked();
        final entries = await _readAndVerifyUnlocked();
        await _verifyOrRepairCheckpointUnlocked(entries);
        return List.unmodifiable(entries);
      });

  @override
  Future<void> verify() => _exclusive(() async {
        await _ensureDataFileUnlocked();
        final entries = await _readAndVerifyUnlocked();
        await _verifyOrRepairCheckpointUnlocked(entries);
      });

  Future<void> _ensureDataFileUnlocked() async {
    await file.parent.create(recursive: true);
    if (!await file.exists()) {
      await file.create(recursive: true);
    }
  }

  Future<List<AuditEntry>> _readAndVerifyUnlocked() async {
    final entries = await _readAllUnlocked();
    await verifyEntries(entries);
    return entries;
  }

  Future<List<AuditEntry>> _readAllUnlocked() async {
    if (!await file.exists()) {
      return const <AuditEntry>[];
    }
    final contents = await file.readAsString();
    if (contents.isNotEmpty && !contents.endsWith('\n')) {
      throw StateError('Audit journal has a torn final record.');
    }
    final entries = <AuditEntry>[];
    final lines = contents.split('\n');
    for (var index = 0; index < lines.length; index++) {
      final line = lines[index].trim();
      if (line.isEmpty) {
        continue;
      }
      try {
        final decoded = jsonDecode(line);
        if (decoded is! Map) {
          throw const FormatException('Audit line is not a JSON object.');
        }
        entries.add(
          AuditEntry.fromJson(
            decoded.map(
              (key, value) => MapEntry(key.toString(), value as Object?),
            ),
          ),
        );
      } on Object catch (error) {
        throw StateError('Invalid audit journal line ${index + 1}: $error');
      }
    }
    return entries;
  }

  Future<void> _verifyOrRepairCheckpointUnlocked(
    List<AuditEntry> entries,
  ) async {
    final checkpointFile = checkpointFileFor(file);
    final journalHead = entries.isEmpty
        ? const _AuditHead(0, '')
        : _AuditHead(entries.length, entries.last.hash);
    if (!await checkpointFile.exists()) {
      await _writeCheckpointUnlocked(journalHead);
      return;
    }

    final Object? decoded;
    try {
      decoded = jsonDecode(await checkpointFile.readAsString());
    } on Object catch (error) {
      throw StateError('Audit checkpoint is unreadable: $error');
    }
    if (decoded is! Map) {
      throw StateError('Audit checkpoint is not an object.');
    }
    final sequence = decoded['sequence'];
    final hash = decoded['hash'];
    final schemaVersion = decoded['schema_version'];
    if (schemaVersion != 1 || sequence is! int || hash is! String) {
      throw StateError('Audit checkpoint has invalid fields.');
    }
    if (sequence < 0 || sequence > entries.length) {
      throw StateError('Audit checkpoint sequence is outside the journal.');
    }
    if (sequence == 0) {
      if (hash.isNotEmpty) {
        throw StateError('Empty audit checkpoint has a non-empty hash.');
      }
    } else if (entries[sequence - 1].hash != hash) {
      throw StateError('Audit checkpoint does not match the hash chain.');
    }

    if (sequence < journalHead.sequence) {
      await _writeCheckpointUnlocked(journalHead);
    }
  }

  Future<void> _writeCheckpointUnlocked(_AuditHead head) async {
    final checkpointFile = checkpointFileFor(file);
    await checkpointFile.parent.create(recursive: true);
    final temporary = File(
      '${checkpointFile.path}.tmp.$pid.${DateTime.now().microsecondsSinceEpoch}',
    );
    await temporary.writeAsString(
      '${canonicalJson(head.toJson())}\n',
      flush: true,
    );
    try {
      await temporary.rename(checkpointFile.path);
    } on FileSystemException {
      if (await checkpointFile.exists()) {
        await checkpointFile.delete();
      }
      await temporary.rename(checkpointFile.path);
    }
  }
}
