import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'audit_checkpoint_authenticator.dart';
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
        sequence < 1 ||
        timestamp is! String ||
        eventType is! String ||
        eventType.trim().isEmpty ||
        previousHash is! String ||
        hash is! String ||
        !_isSha256(hash) ||
        (sequence > 1 && !_isSha256(previousHash)) ||
        (sequence == 1 && previousHash.isNotEmpty)) {
      throw const FormatException('Audit entry has invalid field values.');
    }
    return AuditEntry(
      sequence: sequence,
      timestamp: DateTime.parse(timestamp),
      eventType: eventType,
      payload: Map<String, Object?>.unmodifiable(
        rawPayload.map(
          (key, value) => MapEntry(key.toString(), value as Object?),
        ),
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
    _entries.add(entry);
    return entry;
  }

  @override
  Future<List<AuditEntry>> readAll() async => List<AuditEntry>.unmodifiable(_entries);

  @override
  Future<void> verify() async => verifyEntries(_entries);
}

final class _VerifiedJournal {
  const _VerifiedJournal({required this.entries, required this.recordEnds});

  final List<AuditEntry> entries;
  final List<int> recordEnds;

  int get byteLength => recordEnds.isEmpty ? 0 : recordEnds.last;

  _AuditHead get head => entries.isEmpty
      ? const _AuditHead(sequence: 0, hash: '', byteLength: 0)
      : _AuditHead(
          sequence: entries.last.sequence,
          hash: entries.last.hash,
          byteLength: byteLength,
        );
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
}

final class _AuthenticatedCheckpoint {
  const _AuthenticatedCheckpoint({
    required this.sequence,
    required this.hash,
    required this.byteLength,
    required this.modifiedMicros,
    required this.changedMicros,
    required this.authenticatorId,
    required this.mac,
  });

  final int sequence;
  final String hash;
  final int byteLength;
  final int modifiedMicros;
  final int changedMicros;
  final String authenticatorId;
  final Uint8List mac;

  _AuditHead get head => _AuditHead(
        sequence: sequence,
        hash: hash,
        byteLength: byteLength,
      );

  Map<String, Object?> unsignedJson() => <String, Object?>{
        'schema_version': 3,
        'sequence': sequence,
        'hash': hash,
        'byte_length': byteLength,
        'modified_micros': modifiedMicros,
        'changed_micros': changedMicros,
        'authenticator_id': authenticatorId,
      };

  Map<String, Object?> toJson() => <String, Object?>{
        ...unsignedJson(),
        'mac': _hex(mac),
      };
}

final class _LegacyCheckpoint {
  const _LegacyCheckpoint({
    required this.schemaVersion,
    required this.sequence,
    required this.hash,
    required this.byteLength,
  });

  final int schemaVersion;
  final int sequence;
  final String hash;
  final int? byteLength;
}

/// A process-safe, bounded, tamper-evident JSONL journal.
///
/// The append head is authenticated by a platform-secure HMAC checkpoint. On a
/// normal append, the process cache, authenticated checkpoint, file size,
/// change timestamps, and terminal record must all agree; only the terminal
/// record is then read. Any cache miss, metadata change, or stale checkpoint
/// triggers complete hash-chain verification before another fact is appended.
/// Explicit [initialize], [verify], and [readAll] always verify the full chain.
///
/// This changes normal append cost from repeatedly scanning all prior records to
/// a bounded authenticated-tail path while retaining fail-closed recovery after
/// ordinary file mutation. An attacker capable of restoring filesystem metadata
/// can defer detection of middle-record damage until the next explicit full
/// verification, but cannot forge or advance the checkpoint without the
/// platform-secure key.
final class JsonlAuditJournal with _AuditVerification implements AuditJournal {
  JsonlAuditJournal(
    this.file, {
    required AuditCheckpointAuthenticator checkpointAuthenticator,
    Clock clock = const SystemClock(),
    this.maximumFileBytes = 64 * 1024 * 1024,
    this.maximumEntryBytes = 256 * 1024,
    this.maximumRecordCount = 500000,
    this.allowLegacyCheckpointMigration = false,
  })  : _checkpointAuthenticator = checkpointAuthenticator,
        _clock = clock {
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
    if (maximumRecordCount < 1) {
      throw ArgumentError.value(
        maximumRecordCount,
        'maximumRecordCount',
        'must be positive',
      );
    }
    if (_checkpointAuthenticator.authenticatorId.trim().isEmpty) {
      throw ArgumentError.value(
        _checkpointAuthenticator.authenticatorId,
        'checkpointAuthenticator.authenticatorId',
        'must not be empty',
      );
    }
  }

  static const String contractVersion = 'authenticated-checkpoint-v3';

  final File file;
  final AuditCheckpointAuthenticator _checkpointAuthenticator;
  final Clock _clock;
  final int maximumFileBytes;
  final int maximumEntryBytes;
  final int maximumRecordCount;
  final bool allowLegacyCheckpointMigration;

  static final Map<String, Future<void>> _processTails =
      <String, Future<void>>{};
  static final Map<String, _AuthenticatedCheckpoint> _trustedHeads =
      <String, _AuthenticatedCheckpoint>{};

  int _fullVerificationCount = 0;
  int _fastAppendCount = 0;

  /// Exposed for deterministic performance-contract tests.
  int get fullVerificationCount => _fullVerificationCount;

  /// Exposed for deterministic performance-contract tests.
  int get fastAppendCount => _fastAppendCount;

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
        _trustedHeads.remove(key);
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
        await _fullVerifyAndSynchronizeCheckpointUnlocked();
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
        final head = await _appendHeadUnlocked();
        if (head.sequence >= maximumRecordCount) {
          throw StateError(
            'Audit journal reached its bounded record capacity of '
            '$maximumRecordCount records.',
          );
        }

        final sequence = head.sequence + 1;
        final timestamp = _clock.now().toUtc();
        final immutablePayload = Map<String, Object?>.unmodifiable(payload);
        final hash = AuditEntry.calculateHash(
          sequence: sequence,
          timestamp: timestamp,
          eventType: eventType,
          payload: immutablePayload,
          previousHash: head.hash,
        );
        final entry = AuditEntry(
          sequence: sequence,
          timestamp: timestamp,
          eventType: eventType,
          payload: immutablePayload,
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

        try {
          final stat = await file.stat();
          await _writeCheckpointUnlocked(
            head: _AuditHead(
              sequence: sequence,
              hash: hash,
              byteLength: nextLength,
            ),
            stat: stat,
          );
        } on Object {
          _trustedHeads.remove(file.absolute.path);
          rethrow;
        }
        return entry;
      });

  @override
  Future<List<AuditEntry>> readAll() => _exclusive(() async {
        await _ensureDataFileUnlocked();
        final verified = await _fullVerifyAndSynchronizeCheckpointUnlocked();
        return List<AuditEntry>.unmodifiable(verified.entries);
      });

  @override
  Future<void> verify() => _exclusive(() async {
        await _ensureDataFileUnlocked();
        await _fullVerifyAndSynchronizeCheckpointUnlocked();
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

  Future<_AuditHead> _appendHeadUnlocked() async {
    final checkpointFile = checkpointFileFor(file);
    if (!await checkpointFile.exists()) {
      final length = await file.length();
      if (length != 0) {
        throw StateError(
          'Authenticated audit checkpoint is missing for a non-empty journal.',
        );
      }
      final verified = await _fullVerifyAndSynchronizeCheckpointUnlocked();
      return verified.head;
    }

    final decoded = await _decodeCheckpointUnlocked(checkpointFile);
    if (decoded is _LegacyCheckpoint) {
      final verified = await _fullVerifyAndSynchronizeCheckpointUnlocked();
      return verified.head;
    }
    final checkpoint = decoded as _AuthenticatedCheckpoint;
    final stat = await file.stat();
    final trusted = _trustedHeads[file.absolute.path];
    if (_checkpointMatchesStat(checkpoint, stat) &&
        trusted != null &&
        _sameCheckpoint(trusted, checkpoint)) {
      final tail = await _readTerminalEntryUnlocked();
      _verifyTerminalAgainstCheckpoint(tail, checkpoint);
      _fastAppendCount++;
      return checkpoint.head;
    }

    final verified = await _fullVerifyAndSynchronizeCheckpointUnlocked(
      decodedCheckpoint: decoded,
    );
    return verified.head;
  }

  Future<_VerifiedJournal> _fullVerifyAndSynchronizeCheckpointUnlocked({
    Object? decodedCheckpoint,
  }) async {
    _fullVerificationCount++;
    final verified = await _readAndVerifyUnlocked();
    final checkpointFile = checkpointFileFor(file);
    Object? decoded = decodedCheckpoint;
    if (decoded == null && await checkpointFile.exists()) {
      decoded = await _decodeCheckpointUnlocked(checkpointFile);
    }

    if (decoded == null) {
      if (verified.entries.isNotEmpty) {
        throw StateError(
          'Authenticated audit checkpoint is missing for a non-empty journal.',
        );
      }
      await _writeCheckpointUnlocked(
        head: verified.head,
        stat: await file.stat(),
      );
      return verified;
    }

    if (decoded is _LegacyCheckpoint) {
      if (!allowLegacyCheckpointMigration) {
        throw StateError(
          'Legacy audit checkpoint requires explicit offline migration.',
        );
      }
      _verifyLegacyCheckpointAgainstJournal(decoded, verified);
      await _writeCheckpointUnlocked(
        head: verified.head,
        stat: await file.stat(),
      );
      return verified;
    }

    final checkpoint = decoded as _AuthenticatedCheckpoint;
    _verifyCheckpointAnchor(checkpoint, verified);
    final stat = await file.stat();
    final currentHead = verified.head;
    final isCurrentHead = checkpoint.sequence == currentHead.sequence &&
        checkpoint.hash == currentHead.hash &&
        checkpoint.byteLength == currentHead.byteLength;
    if (!isCurrentHead || !_checkpointMatchesStat(checkpoint, stat)) {
      await _writeCheckpointUnlocked(head: currentHead, stat: stat);
    } else {
      _trustedHeads[file.absolute.path] = checkpoint;
    }
    return verified;
  }

  Future<_VerifiedJournal> _readAndVerifyUnlocked() async {
    final verified = await _readAllUnlocked();
    await verifyEntries(verified.entries);
    return verified;
  }

  Future<_VerifiedJournal> _readAllUnlocked() async {
    final bytes = await file.readAsBytes();
    if (bytes.length > maximumFileBytes) {
      throw StateError('Audit journal exceeds its bounded capacity.');
    }
    if (bytes.isNotEmpty && bytes.last != 0x0a) {
      throw StateError('Audit journal has a torn final record.');
    }

    final entries = <AuditEntry>[];
    final recordEnds = <int>[];
    var recordStart = 0;
    for (var index = 0; index < bytes.length; index++) {
      if (bytes[index] != 0x0a) {
        continue;
      }
      final recordLength = index - recordStart + 1;
      if (recordLength <= 1) {
        throw StateError('Audit journal contains an empty record.');
      }
      if (recordLength > maximumEntryBytes) {
        throw StateError(
          'Audit journal record ${entries.length + 1} is oversized.',
        );
      }
      if (entries.length >= maximumRecordCount) {
        throw StateError('Audit journal exceeds its bounded record capacity.');
      }
      final line = utf8.decode(bytes.sublist(recordStart, index));
      entries.add(_decodeEntry(line, entries.length + 1));
      recordEnds.add(index + 1);
      recordStart = index + 1;
    }
    if (recordStart != bytes.length) {
      throw StateError('Audit journal has a torn final record.');
    }
    return _VerifiedJournal(
      entries: List<AuditEntry>.unmodifiable(entries),
      recordEnds: List<int>.unmodifiable(recordEnds),
    );
  }

  AuditEntry _decodeEntry(String line, int lineNumber) {
    try {
      final decoded = jsonDecode(line);
      if (decoded is! Map) {
        throw const FormatException('Audit line is not a JSON object.');
      }
      return AuditEntry.fromJson(
        decoded.map(
          (key, value) => MapEntry(key.toString(), value as Object?),
        ),
      );
    } on Object catch (error) {
      throw StateError('Invalid audit journal line $lineNumber: $error');
    }
  }

  Future<AuditEntry?> _readTerminalEntryUnlocked() async {
    final length = await file.length();
    if (length == 0) {
      return null;
    }
    final readLength = length > maximumEntryBytes + 1
        ? maximumEntryBytes + 1
        : length;
    final start = length - readLength;
    final handle = await file.open();
    final Uint8List bytes;
    try {
      await handle.setPosition(start);
      bytes = await handle.read(readLength);
    } finally {
      await handle.close();
    }
    if (bytes.isEmpty || bytes.last != 0x0a) {
      throw StateError('Audit journal has a torn final record.');
    }
    var previousNewline = -1;
    for (var index = bytes.length - 2; index >= 0; index--) {
      if (bytes[index] == 0x0a) {
        previousNewline = index;
        break;
      }
    }
    if (start > 0 && previousNewline < 0) {
      throw StateError('Audit terminal record exceeds its bounded size.');
    }
    final recordStart = previousNewline + 1;
    final recordLength = bytes.length - recordStart;
    if (recordLength <= 1 || recordLength > maximumEntryBytes) {
      throw StateError('Audit terminal record has an invalid size.');
    }
    final line = utf8.decode(bytes.sublist(recordStart, bytes.length - 1));
    return _decodeEntry(line, -1);
  }

  Future<Object> _decodeCheckpointUnlocked(File checkpointFile) async {
    final text = await checkpointFile.readAsString();
    final Object? decodedJson;
    try {
      decodedJson = jsonDecode(text.trim());
    } on Object catch (error) {
      throw StateError('Audit checkpoint is invalid JSON: $error');
    }
    if (decodedJson is! Map) {
      throw StateError('Audit checkpoint is not an object.');
    }
    final document = decodedJson.map(
      (key, value) => MapEntry(key.toString(), value as Object?),
    );
    final schemaVersion = document['schema_version'];
    if (schemaVersion is! int) {
      throw StateError('Audit checkpoint schema version is invalid.');
    }
    if (schemaVersion == 1 || schemaVersion == 2) {
      final sequence = document['sequence'];
      final hash = document['hash'];
      final byteLength = document['byte_length'];
      if (sequence is! int ||
          sequence < 0 ||
          hash is! String ||
          (sequence == 0 && hash.isNotEmpty) ||
          (sequence > 0 && !_isSha256(hash)) ||
          (byteLength != null && (byteLength is! int || byteLength < 0))) {
        throw StateError('Legacy audit checkpoint fields are invalid.');
      }
      return _LegacyCheckpoint(
        schemaVersion: schemaVersion,
        sequence: sequence,
        hash: hash,
        byteLength: byteLength as int?,
      );
    }
    if (schemaVersion != 3) {
      throw StateError('Unsupported audit checkpoint schema $schemaVersion.');
    }

    final sequence = document['sequence'];
    final hash = document['hash'];
    final byteLength = document['byte_length'];
    final modifiedMicros = document['modified_micros'];
    final changedMicros = document['changed_micros'];
    final authenticatorId = document['authenticator_id'];
    final macHex = document['mac'];
    if (sequence is! int ||
        sequence < 0 ||
        hash is! String ||
        (sequence == 0 && hash.isNotEmpty) ||
        (sequence > 0 && !_isSha256(hash)) ||
        byteLength is! int ||
        byteLength < 0 ||
        byteLength > maximumFileBytes ||
        modifiedMicros is! int ||
        modifiedMicros < 0 ||
        changedMicros is! int ||
        changedMicros < 0 ||
        authenticatorId is! String ||
        authenticatorId != _checkpointAuthenticator.authenticatorId ||
        macHex is! String ||
        !RegExp(r'^[0-9a-f]{64}$').hasMatch(macHex)) {
      throw StateError('Authenticated audit checkpoint fields are invalid.');
    }
    final checkpoint = _AuthenticatedCheckpoint(
      sequence: sequence,
      hash: hash,
      byteLength: byteLength,
      modifiedMicros: modifiedMicros,
      changedMicros: changedMicros,
      authenticatorId: authenticatorId,
      mac: _hexDecode(macHex),
    );
    final expected = await _checkpointAuthenticator.authenticate(
      Uint8List.fromList(utf8.encode(canonicalJson(checkpoint.unsignedJson()))),
    );
    if (!constantTimeBytesEqual(expected, checkpoint.mac)) {
      throw StateError('Audit checkpoint authentication failed.');
    }
    return checkpoint;
  }

  void _verifyCheckpointAnchor(
    _AuthenticatedCheckpoint checkpoint,
    _VerifiedJournal journal,
  ) {
    if (checkpoint.sequence == 0) {
      if (checkpoint.hash.isNotEmpty || checkpoint.byteLength != 0) {
        throw StateError('Empty audit checkpoint is malformed.');
      }
      return;
    }
    if (checkpoint.sequence > journal.entries.length) {
      throw StateError('Audit journal is shorter than its checkpoint.');
    }
    final index = checkpoint.sequence - 1;
    if (journal.entries[index].hash != checkpoint.hash ||
        journal.recordEnds[index] != checkpoint.byteLength) {
      throw StateError('Audit checkpoint does not authenticate its journal prefix.');
    }
  }

  void _verifyLegacyCheckpointAgainstJournal(
    _LegacyCheckpoint checkpoint,
    _VerifiedJournal journal,
  ) {
    if (checkpoint.sequence == 0) {
      if (checkpoint.hash.isNotEmpty ||
          (checkpoint.byteLength != null && checkpoint.byteLength != 0)) {
        throw StateError('Legacy empty audit checkpoint is malformed.');
      }
      return;
    }
    if (checkpoint.sequence > journal.entries.length) {
      throw StateError('Audit journal is shorter than its legacy checkpoint.');
    }
    final index = checkpoint.sequence - 1;
    if (journal.entries[index].hash != checkpoint.hash) {
      throw StateError('Legacy audit checkpoint hash mismatch.');
    }
    if (checkpoint.schemaVersion == 2 &&
        checkpoint.byteLength != journal.recordEnds[index]) {
      throw StateError('Legacy audit checkpoint byte-length mismatch.');
    }
  }

  void _verifyTerminalAgainstCheckpoint(
    AuditEntry? terminal,
    _AuthenticatedCheckpoint checkpoint,
  ) {
    if (checkpoint.sequence == 0) {
      if (terminal != null || checkpoint.byteLength != 0) {
        throw StateError('Empty checkpoint does not match the journal.');
      }
      return;
    }
    if (terminal == null ||
        terminal.sequence != checkpoint.sequence ||
        terminal.hash != checkpoint.hash) {
      throw StateError('Audit checkpoint does not match the terminal record.');
    }
    final calculated = AuditEntry.calculateHash(
      sequence: terminal.sequence,
      timestamp: terminal.timestamp,
      eventType: terminal.eventType,
      payload: terminal.payload,
      previousHash: terminal.previousHash,
    );
    if (calculated != terminal.hash) {
      throw StateError('Audit terminal record hash is invalid.');
    }
  }

  Future<void> _writeCheckpointUnlocked({
    required _AuditHead head,
    required FileStat stat,
  }) async {
    if (head.byteLength != stat.size) {
      throw StateError('Audit checkpoint byte length does not match the journal.');
    }
    final unsigned = _AuthenticatedCheckpoint(
      sequence: head.sequence,
      hash: head.hash,
      byteLength: head.byteLength,
      modifiedMicros: _micros(stat.modified),
      changedMicros: _micros(stat.changed),
      authenticatorId: _checkpointAuthenticator.authenticatorId,
      mac: Uint8List(0),
    );
    final mac = await _checkpointAuthenticator.authenticate(
      Uint8List.fromList(utf8.encode(canonicalJson(unsigned.unsignedJson()))),
    );
    if (mac.length != 32) {
      throw StateError('Audit checkpoint authenticator returned invalid output.');
    }
    final checkpoint = _AuthenticatedCheckpoint(
      sequence: unsigned.sequence,
      hash: unsigned.hash,
      byteLength: unsigned.byteLength,
      modifiedMicros: unsigned.modifiedMicros,
      changedMicros: unsigned.changedMicros,
      authenticatorId: unsigned.authenticatorId,
      mac: Uint8List.fromList(mac),
    );
    final checkpointFile = checkpointFileFor(file);
    await checkpointFile.parent.create(recursive: true);
    final temporary = File('${checkpointFile.path}.tmp');
    await temporary.writeAsString(
      '${canonicalJson(checkpoint.toJson())}\n',
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
    _trustedHeads[file.absolute.path] = checkpoint;
  }

  bool _checkpointMatchesStat(
    _AuthenticatedCheckpoint checkpoint,
    FileStat stat,
  ) =>
      checkpoint.byteLength == stat.size &&
      checkpoint.modifiedMicros == _micros(stat.modified) &&
      checkpoint.changedMicros == _micros(stat.changed);

  bool _sameCheckpoint(
    _AuthenticatedCheckpoint left,
    _AuthenticatedCheckpoint right,
  ) =>
      left.sequence == right.sequence &&
      left.hash == right.hash &&
      left.byteLength == right.byteLength &&
      left.modifiedMicros == right.modifiedMicros &&
      left.changedMicros == right.changedMicros &&
      left.authenticatorId == right.authenticatorId &&
      constantTimeBytesEqual(left.mac, right.mac);
}

bool _isSha256(String value) => RegExp(r'^[0-9a-f]{64}$').hasMatch(value);

int _micros(DateTime value) => value.toUtc().microsecondsSinceEpoch;

String _hex(List<int> bytes) => bytes
    .map((int value) => value.toRadixString(16).padLeft(2, '0'))
    .join();

Uint8List _hexDecode(String value) {
  if (value.length.isOdd || !RegExp(r'^[0-9a-f]*$').hasMatch(value)) {
    throw const FormatException('Invalid hexadecimal value.');
  }
  return Uint8List.fromList(
    List<int>.generate(
      value.length ~/ 2,
      (int index) => int.parse(
        value.substring(index * 2, index * 2 + 2),
        radix: 16,
      ),
      growable: false,
    ),
  );
}
