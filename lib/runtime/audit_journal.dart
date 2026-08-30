import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';

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
    return AuditEntry(
      sequence: json['sequence']! as int,
      timestamp: DateTime.parse(json['timestamp']! as String),
      eventType: json['event_type']! as String,
      payload: rawPayload.map(
        (key, value) => MapEntry(key.toString(), value as Object?),
      ),
      previousHash: json['previous_hash']! as String,
      hash: json['hash']! as String,
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

/// A bounded, fail-closed JSONL audit journal.
///
/// The per-instance queue protects callers sharing one object. A short-lived,
/// atomically-created marker protects cooperating writers across Dart isolates
/// and processes, including platforms where advisory file locks are
/// process-scoped. The journal file itself is also locked and all reads and
/// writes use the same [RandomAccessFile] handle for Windows compatibility.
///
/// A torn tail, malformed record, forked hash chain, oversized record, or
/// exhausted journal fails closed. Recovery never silently truncates evidence.
final class JsonlAuditJournal with _AuditVerification implements AuditJournal {
  JsonlAuditJournal(
    File file, {
    Clock clock = const SystemClock(),
    this.maxBytes = 8 * 1024 * 1024,
    this.maxEntries = 50000,
    this.maxEntryBytes = 64 * 1024,
    this.lockAcquireTimeout = const Duration(seconds: 10),
    this.staleLockAge = const Duration(minutes: 2),
    this.lockRetryDelay = const Duration(milliseconds: 10),
  })  : file = File(file.absolute.path),
        _lockFile = File('${file.absolute.path}.lock'),
        _clock = clock {
    if (maxBytes <= 0 || maxEntries <= 0 || maxEntryBytes <= 0) {
      throw ArgumentError('Audit journal bounds must be positive.');
    }
    if (maxEntryBytes > maxBytes) {
      throw ArgumentError('maxEntryBytes cannot exceed maxBytes.');
    }
    if (lockAcquireTimeout <= Duration.zero ||
        staleLockAge <= lockAcquireTimeout ||
        lockRetryDelay <= Duration.zero) {
      throw ArgumentError('Audit journal lock durations are invalid.');
    }
  }

  final File file;
  final File _lockFile;
  final Clock _clock;
  final int maxBytes;
  final int maxEntries;
  final int maxEntryBytes;
  final Duration lockAcquireTimeout;
  final Duration staleLockAge;
  final Duration lockRetryDelay;

  Future<void> _tail = Future<void>.value();

  Future<T> _exclusive<T>(Future<T> Function() operation) {
    final completer = Completer<T>();
    _tail = _tail.then((_) async {
      try {
        completer.complete(await operation());
      } on Object catch (error, stackTrace) {
        completer.completeError(error, stackTrace);
      }
    });
    return completer.future;
  }

  Future<void> initialize() =>
      _exclusive(() => _withLockedHandle((handle) async {
            await verifyEntries(await _readAllFromHandle(handle));
          }));

  @override
  Future<AuditEntry> append(
    String eventType,
    Map<String, Object?> payload,
  ) =>
      _exclusive(() => _withLockedHandle((handle) async {
            if (eventType.trim().isEmpty) {
              throw ArgumentError.value(
                eventType,
                'eventType',
                'must not be empty',
              );
            }

            final entries = await _readAllFromHandle(handle);
            await verifyEntries(entries);
            if (entries.length >= maxEntries) {
              throw StateError(
                'Audit journal reached its configured entry limit.',
              );
            }

            final sequence = entries.length + 1;
            final previousHash = entries.isEmpty ? '' : entries.last.hash;
            final timestamp = _clock.now().toUtc();
            final immutablePayload = Map<String, Object?>.unmodifiable(payload);
            final hash = AuditEntry.calculateHash(
              sequence: sequence,
              timestamp: timestamp,
              eventType: eventType,
              payload: immutablePayload,
              previousHash: previousHash,
            );
            final entry = AuditEntry(
              sequence: sequence,
              timestamp: timestamp,
              eventType: eventType,
              payload: immutablePayload,
              previousHash: previousHash,
              hash: hash,
            );
            final encoded = utf8.encode('${canonicalJson(entry.toJson())}\n');
            if (encoded.length > maxEntryBytes) {
              throw StateError(
                'Audit entry exceeds the configured byte limit.',
              );
            }

            final currentLength = await handle.length();
            if (currentLength + encoded.length > maxBytes) {
              throw StateError(
                'Audit journal reached its configured byte limit.',
              );
            }
            await handle.setPosition(currentLength);
            await handle.writeFrom(encoded);
            await handle.flush();
            return entry;
          }));

  @override
  Future<List<AuditEntry>> readAll() =>
      _exclusive(() => _withLockedHandle((handle) async {
            final entries = await _readAllFromHandle(handle);
            await verifyEntries(entries);
            return List<AuditEntry>.unmodifiable(entries);
          }));

  @override
  Future<void> verify() =>
      _exclusive(() => _withLockedHandle((handle) async {
            await verifyEntries(await _readAllFromHandle(handle));
          }));

  Future<T> _withLockedHandle<T>(
    Future<T> Function(RandomAccessFile handle) operation,
  ) async {
    await file.parent.create(recursive: true);
    final markerToken = await _acquireMarker();
    RandomAccessFile? handle;
    var fileLocked = false;
    try {
      handle = await file.open(mode: FileMode.append);
      await handle.lock(FileLock.blockingExclusive);
      fileLocked = true;
      return await operation(handle);
    } finally {
      if (handle != null) {
        try {
          if (fileLocked) {
            await handle.unlock();
          }
        } finally {
          await handle.close();
        }
      }
      await _releaseMarker(markerToken);
    }
  }

  Future<List<AuditEntry>> _readAllFromHandle(
    RandomAccessFile handle,
  ) async {
    final length = await handle.length();
    if (length > maxBytes) {
      throw StateError('Audit journal exceeds its configured byte limit.');
    }
    if (length == 0) {
      return const <AuditEntry>[];
    }

    await handle.setPosition(0);
    final bytes = await handle.read(length);
    late final String text;
    try {
      text = utf8.decode(bytes, allowMalformed: false);
    } on FormatException catch (error) {
      throw StateError('Audit journal is not valid UTF-8: $error');
    }
    if (!text.endsWith('\n')) {
      throw StateError('Audit journal has a torn final record.');
    }

    final entries = <AuditEntry>[];
    final lines = text.split('\n');
    for (var index = 0; index < lines.length - 1; index++) {
      final line = lines[index];
      if (line.isEmpty) {
        throw StateError('Audit journal contains an empty record.');
      }
      if (utf8.encode(line).length + 1 > maxEntryBytes) {
        throw StateError(
          'Audit journal line ${index + 1} exceeds the configured byte limit.',
        );
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
      if (entries.length > maxEntries) {
        throw StateError('Audit journal exceeds its configured entry limit.');
      }
    }
    return entries;
  }

  Future<String> _acquireMarker() async {
    final deadline = DateTime.now().toUtc().add(lockAcquireTimeout);
    while (true) {
      final now = DateTime.now().toUtc();
      final token = _newMarkerToken(now);
      try {
        await _lockFile.create(exclusive: true);
        await _lockFile.writeAsString('$token\n', flush: true);
        return token;
      } on FileSystemException {
        if (await _breakStaleMarker(now)) {
          continue;
        }
        if (!DateTime.now().toUtc().isBefore(deadline)) {
          throw StateError(
            'Timed out acquiring the durable audit journal lock.',
          );
        }
        await Future<void>.delayed(lockRetryDelay);
      }
    }
  }

  String _newMarkerToken(DateTime now) {
    final random = Random.secure().nextInt(1 << 32);
    return '$pid:${now.microsecondsSinceEpoch}:$random';
  }

  Future<bool> _breakStaleMarker(DateTime now) async {
    FileStat stat;
    try {
      stat = await _lockFile.stat();
    } on FileSystemException {
      return false;
    }
    if (stat.type == FileSystemEntityType.notFound ||
        now.difference(stat.modified.toUtc()) < staleLockAge) {
      return stat.type == FileSystemEntityType.notFound;
    }

    final stale = File(
      '${_lockFile.path}.stale.$pid.${now.microsecondsSinceEpoch}',
    );
    try {
      await _lockFile.rename(stale.path);
      await stale.delete();
      return true;
    } on FileSystemException {
      return false;
    }
  }

  Future<void> _releaseMarker(String token) async {
    try {
      if (!await _lockFile.exists()) {
        return;
      }
      final stored = (await _lockFile.readAsString()).trim();
      if (stored == token) {
        await _lockFile.delete();
      }
    } on FileSystemException {
      // The journal write has already been flushed. A stale marker is safe:
      // the bounded takeover path will recover it without altering evidence.
    }
  }
}
