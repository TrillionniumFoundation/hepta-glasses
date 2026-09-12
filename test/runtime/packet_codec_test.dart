import 'dart:io';
import 'dart:typed_data';

import 'package:hepta_glasses/runtime/packet_codec.dart';
import 'package:hepta_glasses/runtime/strict_json.dart';
import 'package:flutter_test/flutter_test.dart';

part 'packet_codec_contract_support.dart';
part 'packet_codec_generated_support.dart';

void main() {
  const codec = PacketCodec();
  final contract = _loadContract();

  test('shared positive vectors fragment and reassemble exactly', () {
    for (final vector in contract.vectors) {
      final fragmented = codec.fragment(
        command: vector.command,
        payload: vector.payload,
        maxPacketBytes: vector.maxPacketBytes,
        metadata: vector.metadata,
      );
      expect(
        fragmented.map(_toHex).toList(),
        vector.frames.map(_toHex).toList(),
        reason: vector.id,
      );

      final reversed = fragmented.reversed.toList();
      expect(
        codec.reassemble(
          reversed,
          expectedCommand: vector.command,
          metadataLength: vector.metadata.length,
        ),
        vector.payload,
        reason: vector.id,
      );
    }
  });

  test('shared negative vectors reach their exact rejection branches', () {
    for (final vector in contract.negativeVectors) {
      expect(
        () => codec.reassemble(
          vector.frames,
          expectedCommand: vector.expectedCommand,
          metadataLength: vector.metadataLength,
        ),
        throwsA(
          isA<FormatException>().having(
            (error) => error.message,
            'message',
            vector.expectedError,
          ),
        ),
        reason: vector.id,
      );
    }
  });

  test('generated families execute their exact declared case counts', () {
    var executed = 0;
    for (final family in contract.generatedFamilies) {
      final random = _Lcg(family.seed);
      for (var index = 0; index < family.cases; index++) {
        _runGeneratedCase(codec, family.id, random);
        executed += 1;
      }
    }
    expect(
      executed,
      contract.generatedFamilies.fold<int>(
        0,
        (total, family) => total + family.cases,
      ),
    );
  });

  test('frame and metadata construction boundaries remain closed', () {
    expect(
      () => codec.fragment(
        command: -1,
        payload: Uint8List(0),
      ),
      throwsRangeError,
    );
    expect(
      () => codec.fragment(
        command: 0,
        payload: Uint8List(0),
        metadata: const <int>[256],
      ),
      throwsRangeError,
    );
    expect(
      () => codec.fragment(
        command: 0,
        payload: Uint8List(256),
        maxPacketBytes: 4,
      ),
      throwsStateError,
    );
    expect(
      () => codec.reassemble(
        <Uint8List>[
          Uint8List.fromList(const <int>[0, 1, 0])
        ],
        metadataLength: -1,
      ),
      throwsArgumentError,
    );
  });

  test(
    'dedicated duplicate-sequence semantic mutant is killed',
    () async {
      final source = File('lib/runtime/packet_codec.dart').readAsStringSync();
      const needle = 'if (ordered[sequence] != null) {';
      const replacement = 'if (false) {';
      expect(needle.allMatches(source).length, 1);
      expect(source.contains(replacement), isFalse);

      final directory = Directory.systemTemp.createTempSync(
        'hepta-packet-mutant-',
      );
      addTearDown(() => directory.deleteSync(recursive: true));

      final canonical = File('${directory.path}/packet_codec_canonical.dart')
        ..writeAsStringSync(source);
      final mutant = File('${directory.path}/packet_codec_mutant.dart')
        ..writeAsStringSync(source.replaceFirst(needle, replacement));
      final canonicalMain = File('${directory.path}/canonical_main.dart')
        ..writeAsStringSync(_mutantHarness(canonical.uri.pathSegments.last));
      final mutantMain = File('${directory.path}/mutant_main.dart')
        ..writeAsStringSync(_mutantHarness(mutant.uri.pathSegments.last));

      final canonicalRun = await Process.run(
        'dart',
        <String>[canonicalMain.path],
        workingDirectory: directory.path,
      );
      expect(
        canonicalRun.exitCode,
        0,
        reason: '${canonicalRun.stdout}\n${canonicalRun.stderr}',
      );

      final mutantRun = await Process.run(
        'dart',
        <String>[mutantMain.path],
        workingDirectory: directory.path,
      );
      expect(mutantRun.exitCode, isNot(0));
      expect(
        '${mutantRun.stdout}\n${mutantRun.stderr}',
        contains('Missing frame sequence.'),
      );
    },
    timeout: const Timeout(Duration(minutes: 1)),
  );
}
