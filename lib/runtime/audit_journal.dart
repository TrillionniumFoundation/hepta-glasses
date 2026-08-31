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
  Future<AuditEntry> append(String eventType, Map<String, Object?> payload);

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
  const _AuditHead({
    required this.sequence,
    required this.hash,
    required this.byteLength,
  });

  final int sequence;
  final String hash;
  final int byteLength;

  Map<String, Object?> toJson() => <String, Object?>{
        'schema_version': 2,
        'sequence': sequence,
        'hash': hash,
        'byte_length': byteLength,
      };
}

final class _DecodedCheckpoint {
  const _DecodedCheckpoint({
    required this.schemaVersion,
    required this.sequence,
    required this.hash,
    this.byteLength,
  });

  final int schemaVersion;
  final int sequence;
  final String hash;
  final int? byteLength;
}

/// A process-safe bounded JSONL journal.
///
/// Startup, recovery, explicit verification, full reads, and every append
/// validate the complete hash chain. The v2 checkpoint and exact byte length are
/// crash-recovery hints, never standalone integrity roots. A crash after journal
/// flush but before checkpoint replacement is repaired only after the full chain
/// has been authenticated under both the process lane and the OS file lock.
final class JsonlAuditJournal with _AuditVerification implements AuditJournal {
  JsonlAuditJournal(
    this.file, {
    Clock clock = const SystemClock(),
    this.maximumFileBytes = 64 * 1024 * 1024,
    this.maximumEntryBytes = 256 * 1024,
  }) : _clock = clock {
    if (maximumEntryBytes < 1024) {
      throw ArgumentError.value(
        maximumEntryBytes,
        'maximumEntryBytes',
        'must be at least 1024 bytes',
      );
    }
    if (maximumFileBytes < maximumEntryBytes) {
      throw ArgumentError.value(
        maximumFileBytes,
        'maximumFileBytes',
        'must be at least maximumEntryBytes',
      );
    }
  }

  static const String contractVersion = 'file-lock-checkpoint-v2';

  final File file;
  final Clock _clock;
  final int maximumFileBytes;
  final int maximumEntryBytes;

  // POSIX advisory locks can be process-associated on some runtimes, so two
  // File handles opened by the same process must also share a Dart-level lane.
  // The absolute path makes separate journal instances serialize before taking
  // the operating-system lock.
  static final Map<String, Future<void>> _processTails =
      <String, Future<void>>{};

  static File lockFileFor(File file) => File('${file.path}.lock');
  static File checkpointFileFor(File file) => File('${file.path}.head.json');

  Future<T> _exclusive<T>(Future<T> Function() operation) {
    final completer = Completer<T>();
    final key = file.absolute.path;
    final previous = _processTails[key] ?? Future<void>.value();
    late final Future<void> queued;
    queued = previous.then<void>((_) async {
      try {
        completer.complete(await _withFileLock(operation));
      } on Object catch (error, stackTrace) {
        completer.completeError(error, stackTrace);
      }
    }).whenComplete(() {
      if (identical(_processTails[key], queued)) {
        _processTails.remove(key);
      }
    });
    _processTails[key] = queued;
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
  Future<AuditEntry> append(String eventType, Map<String, Object?> payload) =>
      _exclusive(() async {
        if (eventType.trim().isEmpty) {
          throw ArgumentError.value(
            eventType,
            'eventType',
            'must not be empty',
          );
        }
        await _ensureDataFileUnlocked();
        // Authenticate all prior records before creating a new audit fact. A
        // checkpoint that matches only the file length and terminal record is
        // insufficient because a same-length middle record may have changed.
        final entries = await _readAndVerifyUnlocked();
        await _verifyOrRepairCheckpointUnlocked(entries);
        final head = await _loadAppendHeadUnlocked();

        final sequence = head.sequence + 1;
        final timestamp = _clock.now().toUtc();
        final hash = AuditEntry.calculateHash(
          sequence: sequence,
          timestamp: timestamp,
          eventType: eventType,
          payload: payload,
          previousHash: head.hash,
        );
        final entry = AuditEntry(
          sequence: sequence,
          timestamp: timestamp,
          eventType: eventType,
          payload: Map.unmodifiable(payload),
          previousHash: head.hash,
          hash: hash,
        );
        final encoded = utf8.encode('${canonicalJson(entry.toJson())}\n');
        if (encoded.length > maximumEntryBytes) {
          throw StateError(
            'Audit entry exceeds the bounded entry size of '
            '$maximumEntryBytes bytes.',
          );
        }
        final nextLength = head.byteLength + encoded.length;
        if (nextLength > maximumFileBytes) {
          throw StateError(
            'Audit journal reached its bounded capacity of '
            '$maximumFileBytes bytes.',
          );
        }

        final handle = await file.open(mode: FileMode.append);
        try {
          await handle.writeFrom(encoded);
          await handle.flush();
        } finally {
          await handle.close();
        }
        await _writeCheckpointUnlocked(
          _AuditHead(sequence: sequence, hash: hash, byteLength: nextLength),
        );
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
    final length = await file.length();
    if (length > maximumFileBytes) {
      throw StateError('Audit journal exceeds its bounded capacity.');
    }
  }

  Future<_AuditHead> _loadAppendHeadUnlocked() async {
    final checkpointFile = checkpointFileFor(file);
    if (!await checkpointFile.exists()) {
      return _rebuildAppendHeadUnlocked();
    }

    final checkpoint = await _decodeCheckpointUnlocked(checkpointFile);
    if (checkpoint.schemaVersion != 2 || checkpoint.byteLength == null) {
      return _rebuildAppendHeadUnlocked(expected: checkpoint);
    }

    final actualLength = await file.length();
    final checkpointLength = checkpoint.byteLength!;
    if (checkpointLength < 0 || checkpointLength > maximumFileBytes) {
      throw StateError('Audit checkpoint byte length is invalid.');
    }
    if (actualLength < checkpointLength) {
      throw StateError('Audit journal is shorter than its checkpoint.');
    }
    if (actualLength > checkpointLength) {
      return _rebuildAppendHeadUnlocked(expected: checkpoint);
    }

    if (checkpoint.sequence == 0) {
      if (checkpoint.hash.isNotEmpty || actualLength != 0) {
        throw StateError('Empty audit checkpoint does not match the journal.');
      }
      return const _AuditHead(sequence: 0, hash: '', byteLength: 0);
    }
    if (checkpoint.sequence < 0 || checkpoint.hash.isEmpty) {
      throw StateError('Audit checkpoint head is invalid.');
    }

    final tail = await _readTerminalEntryUnlocked();
    if (tail == null ||
        tail.sequence != checkpoint.sequence ||
        tail.hash != checkpoint.hash) {
      throw StateError('Audit checkpoint does not match the terminal record.');
    }
    final calculated = AuditEntry.calculateHash(
      sequence: tail.sequence,
      timestamp: tail.timestamp,
      eventType: tail.eventType,
      payload: tail.payload,
      previousHash: tail.previousHash,
    );
    if (calculated != tail.hash) {
      throw StateError('Audit terminal record hash is invalid.');
    }
    return _AuditHead(
      sequence: checkpoint.sequence,
      hash: checkpoint.hash,
      byteLength: actualLength,
    );
  }

  Future<_AuditHead> _rebuildAppendHeadUnlocked({
    _DecodedCheckpoint? expected,
  }) async {
    final entries = await _readAndVerifyUnlocked();
    if (expected != null) {
      _verifyCheckpointAgainstEntries(expected, entries);
    }
    final head = await _headForEntriesUnlocked(entries);
    await _writeCheckpointUnlocked(head);
    return head;
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
      if (utf8.encode(line).length + 1 > maximumEntryBytes) {
        throw StateError('Audit journal line ${index + 1} is oversized.');
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

  Future<AuditEntry?> _readTerminalEntryUnlocked() async {
    final length = await file.length();
    if (length == 0) {
      return null;
    }
    final tailBytes = maximumEntryBytes + 1;
    final start = length > tailBytes ? length - tailBytes : 0;
    final handle = await file.open();
    final List<int> bytes;
    try {
      await handle.setPosition(start);
      bytes = await handle.read(length - start);
    } finally {
      await handle.close();
    }
    if (bytes.isEmpty || bytes.last != 0x0a) {
      throw StateError('Audit journal has a torn final record.');
    }
    final text = utf8.decode(bytes);
    final lines = text.split('\n');
    if (start > 0 && lines.isNotEmpty) {
      lines.removeAt(0);
    }
    final line = lines.reversed.firstWhere(
      (candidate) => candidate.trim().isNotEmpty,
      orElse: () => '',
    );
    if (line.isEmpty) {
      throw StateError('Audit terminal record exceeds the bounded entry size.');
    }
    final decoded = jsonDecode(line);
    if (decoded is! Map) {
      throw StateError('Audit terminal record is not an object.');
    }
    return AuditEntry.fromJson(
      decoded.map((key, value) => MapEntry(key.toString(), value as Object?)),
    );
  }

  Future<void> _verifyOrRepairCheckpointUnlocked(
    List<AuditEntry> entries,
  ) async {
    final checkpointFile = checkpointFileFor(file);
    final head = await _headForEntriesUnlocked(entries);
    if (!await checkpointFile.exists()) {
      await _writeCheckpointUnlocked(head);
      return;
    }

    final checkpoint = await _decodeCheckpointUnlocked(checkpointFile);
    _verifyCheckpointAgainstEntries(checkpoint, entries);
    if (checkpoint.schemaVersion != 2 ||
        checkpoint.byteLength != head.byteLength ||
        checkpoint.sequence != head.sequence ||
        checkpoint.hash != head.hash) {
      await _writeCheckpointUnlocked(head);
    }
  }

  void _verifyCheckpointAgainstEntries(
    _DecodedCheckpoint checkpoint,
    List<AuditEntry> entries,
  ) {
    if (checkpoint.sequence < 0 || checkpoint.sequence > entries.length) {
      throw StateError('Audit checkpoint sequence is outside the journal.');
    }
    if (checkpoint.sequence == 0) {
      if (checkpoint.hash.isNotEmpty) {
        throw StateError('Empty audit checkpoint has a non-empty hash.');
      }
    } else if (entries[checkpoint.sequence - 1].hash != checkpoint.hash) {
      throw StateError('Audit checkpoint does not match the hash chain.');
    }
  }

  Future<_AuditHead> _headForEntriesUnlocked(List<AuditEntry> entries) async {
    final length = await file.length();
    return entries.isEmpty
        ? _AuditHead(sequence: 0, hash: '', byteLength: length)
        : _AuditHead(
            sequence: entries.length,
            hash: entries.last.hash,
            byteLength: length,
          );
  }

  Future<_DecodedCheckpoint> _decodeCheckpointUnlocked(File checkpoint) async {
    final Object? decoded;
    try {
      decoded = jsonDecode(await checkpoint.readAsString());
    } on Object catch (error) {
      throw StateError('Audit checkpoint is unreadable: $error');
    }
    if (decoded is! Map) {
      throw StateError('Audit checkpoint is not an object.');
    }
    final schemaVersion = decoded['schema_version'];
    final sequence = decoded['sequence'];
    final hash = decoded['hash'];
    final byteLength = decoded['byte_length'];
    if ((schemaVersion != 1 && schemaVersion != 2) ||
        sequence is! int ||
        hash is! String ||
        (schemaVersion == 2 && byteLength is! int)) {
      throw StateError('Audit checkpoint has invalid fields.');
    }
    return _DecodedCheckpoint(
      schemaVersion: schemaVersion as int,
      sequence: sequence,
      hash: hash,
      byteLength: byteLength is int ? byteLength : null,
    );
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
