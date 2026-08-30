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

final class JsonlAuditJournal with _AuditVerification implements AuditJournal {
  JsonlAuditJournal(this.file, {Clock clock = const SystemClock()})
      : _clock = clock;

  final File file;
  final Clock _clock;

  Future<void> initialize() async {
    await file.parent.create(recursive: true);
    if (!await file.exists()) {
      await file.create();
    }
    await verify();
  }

  @override
  Future<AuditEntry> append(
    String eventType,
    Map<String, Object?> payload,
  ) async {
    if (eventType.trim().isEmpty) {
      throw ArgumentError.value(eventType, 'eventType', 'must not be empty');
    }
    final entries = await readAll();
    await verifyEntries(entries);
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
    await file.writeAsString(
      '${canonicalJson(entry.toJson())}\n',
      mode: FileMode.append,
      flush: true,
    );
    return entry;
  }

  @override
  Future<List<AuditEntry>> readAll() async {
    if (!await file.exists()) {
      return const <AuditEntry>[];
    }
    final lines = await file.readAsLines();
    final entries = <AuditEntry>[];
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
    return List.unmodifiable(entries);
  }

  @override
  Future<void> verify() async => verifyEntries(await readAll());
}
