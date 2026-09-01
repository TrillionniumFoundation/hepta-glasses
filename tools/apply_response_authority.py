#!/usr/bin/env python3
"""Close the G8 unscoped native BLE response-authority gap fail-closed."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def fail(message: str) -> None:
    raise SystemExit(message)


def read(root: Path, relative: str) -> str:
    path = root / relative
    if not path.is_file():
        fail(f"missing remediation target: {relative}")
    return path.read_text(encoding="utf-8")


def write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def replace_once(root: Path, relative: str, old: str, new: str) -> None:
    text = read(root, relative)
    count = text.count(old)
    if count != 1:
        fail(f"{relative}: expected one replacement, found {count}")
    write(root, relative, text.replace(old, new, 1))


def replace_regex_once(
    root: Path,
    relative: str,
    pattern: str,
    replacement: str,
) -> None:
    text = read(root, relative)
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        fail(f"{relative}: expected one regex replacement, found {count}")
    write(root, relative, updated)


def insert_before_last_closing_brace(
    root: Path,
    relative: str,
    insertion: str,
) -> None:
    text = read(root, relative)
    marker = "\n}\n"
    index = text.rfind(marker)
    if index < 0:
        fail(f"{relative}: final closing brace not found")
    write(root, relative, text[:index] + insertion + text[index:])


def patch_ble_receive(root: Path) -> None:
    relative = "lib/services/ble.dart"
    replace_once(
        root,
        relative,
        """    final rawPairIdentity = map['pairIdentity'];
    if (rawPairIdentity is String && rawPairIdentity.isNotEmpty) {
      response.pairIdentity = rawPairIdentity;
    }
    return response;
  }

  String hexStringData() => data
""",
        """    final rawPairIdentity = map['pairIdentity'];
    if (rawPairIdentity is String) {
      final normalizedPairIdentity = rawPairIdentity.trim();
      if (normalizedPairIdentity.isNotEmpty) {
        response.pairIdentity = normalizedPairIdentity;
      }
    }
    return response;
  }

  bool get hasAuthoritativeIdentity {
    final normalizedPairIdentity = pairIdentity.trim();
    return generation > 0 &&
        normalizedPairIdentity.isNotEmpty &&
        normalizedPairIdentity == pairIdentity &&
        normalizedPairIdentity != unselectedBlePairIdentity;
  }

  String hexStringData() => data
""",
    )


def patch_request_registry(root: Path) -> None:
    relative = "lib/runtime/ble_request_slot.dart"
    replace_once(
        root,
        relative,
        """final class BleRequestKey {
  const BleRequestKey({
    required this.generation,
    required this.side,
    required this.command,
  })  : assert(generation >= 0),
        assert(side == 'L' || side == 'R'),
        assert(command >= 0 && command <= 0xff);

  final int generation;
  final String side;
  final int command;

  @override
  bool operator ==(Object other) =>
      other is BleRequestKey &&
      other.generation == generation &&
      other.side == side &&
      other.command == command;

  @override
  int get hashCode => Object.hash(generation, side, command);

  @override
  String toString() =>
      '$generation:$side:${command.toRadixString(16).padLeft(2, '0')}';
}
""",
        """final class BleRequestKey {
  const BleRequestKey({
    required this.generation,
    required this.pairIdentity,
    required this.side,
    required this.command,
  })  : assert(generation > 0),
        assert(pairIdentity != ''),
        assert(pairIdentity != 'unselected'),
        assert(side == 'L' || side == 'R'),
        assert(command >= 0 && command <= 0xff);

  final int generation;
  final String pairIdentity;
  final String side;
  final int command;

  @override
  bool operator ==(Object other) =>
      other is BleRequestKey &&
      other.generation == generation &&
      other.pairIdentity == pairIdentity &&
      other.side == side &&
      other.command == command;

  @override
  int get hashCode => Object.hash(pairIdentity, generation, side, command);

  @override
  String toString() =>
      '$pairIdentity:$generation:$side:${command.toRadixString(16).padLeft(2, '0')}';
}
""",
    )
    replace_once(
        root,
        relative,
        "/// Owns exactly one waiter for each generation/side/command tuple.\n",
        "/// Owns exactly one waiter for each pair/generation/side/command tuple.\n",
    )
    replace_once(
        root,
        relative,
        """  /// Used only after an authoritative reconciliation of the exact leg.
  void clearQuarantineForGenerationSide(int generation, String side) {
    assert(side == 'L' || side == 'R');
    clearQuarantineWhere(
      (BleRequestKey key) => key.generation == generation && key.side == side,
    );
  }
""",
        """  /// Used only after authoritative reconciliation of the exact pair/leg.
  void clearQuarantineForGenerationSide(
    int generation,
    String pairIdentity,
    String side,
  ) {
    assert(generation > 0);
    assert(pairIdentity.isNotEmpty && pairIdentity != 'unselected');
    assert(side == 'L' || side == 'R');
    clearQuarantineWhere(
      (BleRequestKey key) =>
          key.generation == generation &&
          key.pairIdentity == pairIdentity &&
          key.side == side,
    );
  }
""",
    )


def patch_ble_manager(root: Path) -> None:
    relative = "lib/ble_manager.dart"
    replacement = r'''  void _handleReceivedData(BleReceive response) {
    if (response.type == 'VoiceChunk' || response.data.isEmpty) {
      return;
    }
    if (!response.hasAuthoritativeIdentity) {
      PrivacySafeLog.event(
        'ble_unscoped_response_rejected',
        fields: <String, Object?>{
          'response_generation': response.generation,
          'response_pair_identity': response.pairIdentity,
          'side': response.lr,
        },
      );
      return;
    }
    if (_connectionGeneration <= 0 ||
        _pairIdentity == unselectedBlePairIdentity) {
      PrivacySafeLog.event(
        'ble_response_without_current_authority',
        fields: <String, Object?>{
          'response_generation': response.generation,
          'response_pair_identity': response.pairIdentity,
        },
      );
      return;
    }
    if (response.generation != _connectionGeneration) {
      PrivacySafeLog.event(
        'ble_stale_generation_response',
        fields: <String, Object?>{
          'response_generation': response.generation,
          'current_generation': _connectionGeneration,
        },
      );
      return;
    }
    if (response.pairIdentity != _pairIdentity) {
      PrivacySafeLog.event(
        'ble_stale_pair_response',
        fields: <String, Object?>{
          'response_pair_identity': response.pairIdentity,
          'current_pair_identity': _pairIdentity,
        },
      );
      return;
    }

    final command = response.getCmd();
    if (response.lr != 'L' && response.lr != 'R') {
      PrivacySafeLog.event(
        'ble_response_side_invalid',
        fields: <String, Object?>{'command': command},
      );
      return;
    }

    if (command == 0xF5 && response.data.length > 1) {
      final notifyIndex = response.data[1];
      switch (notifyIndex) {
        case 0:
          App.get.exitAll();
          break;
        case 1:
          if (response.lr == 'L') {
            EvenAI.get.lastPageByTouchpad();
          } else {
            EvenAI.get.nextPageByTouchpad();
          }
          break;
        case 23:
          unawaited(EvenAI.get.toStartEvenAIByOS());
          break;
        case 24:
          unawaited(EvenAI.get.recordOverByOS());
          break;
        default:
          PrivacySafeLog.event(
            'ble_unknown_device_event',
            fields: <String, Object?>{'event_index': notifyIndex},
          );
      }
      return;
    }

    final generation = response.generation;
    final key = BleRequestKey(
      generation: generation,
      pairIdentity: response.pairIdentity,
      side: response.lr,
      command: command,
    );

    if (_requestRegistry.observeLateResponse(key)) {'''
    replace_regex_once(
        root,
        relative,
        r"  void _handleReceivedData\(BleReceive response\) \{.*?    if \(_requestRegistry\.observeLateResponse\(key\)\) \{",
        replacement,
    )
    replace_once(
        root,
        relative,
        "if (pending.generation == generation || pending.generation == 0) {",
        "if (pending.generation == response.generation) {",
    )
    replace_once(
        root,
        relative,
        """    final key = BleRequestKey(
      generation: generation,
      side: side,
      command: data[0],
    );
""",
        """    final key = BleRequestKey(
      generation: generation,
      pairIdentity: pairIdentity,
      side: side,
      command: data[0],
    );
""",
    )
    replace_once(
        root,
        relative,
        """    final generation = manager._connectionGeneration;
    final pairIdentity = manager._pairIdentity;
    final side = lr ?? Proto.lR();
    if (expectedGeneration != null && expectedGeneration != generation) {
""",
        """    final generation = manager._connectionGeneration;
    final pairIdentity = manager._pairIdentity;
    final side = lr ?? Proto.lR();
    if (generation <= 0 || pairIdentity == unselectedBlePairIdentity) {
      return _timeoutResponse(
        effectMayHaveOccurred: false,
        generation: generation,
        pairIdentity: pairIdentity,
        errorCode: 'connection_authority_unavailable',
      );
    }
    if (expectedGeneration != null && expectedGeneration != generation) {
""",
    )
    replace_once(
        root,
        relative,
        """    if (data.isEmpty) {
      return false;
    }
    final manager = get();
    if (expectedGeneration != null &&
""",
        """    if (data.isEmpty) {
      return false;
    }
    final manager = get();
    if (manager._connectionGeneration <= 0 ||
        manager._pairIdentity == unselectedBlePairIdentity) {
      return false;
    }
    if (expectedGeneration != null &&
""",
    )
    replace_once(
        root,
        relative,
        """  static void _startAckTimeout(
    BleRequestKey key,
    BleRequestSlot<BleReceive> pending,
    int requestedTimeoutMs,
    String pairIdentity,
  ) {
""",
        """  static void _startAckTimeout(
    BleRequestKey key,
    BleRequestSlot<BleReceive> pending,
    int requestedTimeoutMs,
  ) {
""",
    )
    text = read(root, relative)
    ack_start = text.index("  static void _startAckTimeout(")
    ack_end = text.index("\n  void _failPendingRequests(", ack_start)
    ack_block = text[ack_start:ack_end].replace(
        "pairIdentity: pairIdentity,", "pairIdentity: key.pairIdentity,"
    ).replace("'pair_identity': pairIdentity,", "'pair_identity': key.pairIdentity,")
    write(root, relative, text[:ack_start] + ack_block + text[ack_end:])
    replace_once(
        root,
        relative,
        "_startAckTimeout(key, pending, timeoutMs, pairIdentity);",
        "_startAckTimeout(key, pending, timeoutMs);",
    )
    replace_once(
        root,
        relative,
        """  void _failPendingRequests(
    String reason, {
    required bool effectMayHaveOccurred,
    int? generation,
    String? side,
  }) {
    final entries = _requestRegistry.takePendingWhere(
      (BleRequestKey key) =>
          (generation == null || key.generation == generation) &&
          (side == null || key.side == side),
""",
        """  void _failPendingRequests(
    String reason, {
    required bool effectMayHaveOccurred,
    int? generation,
    String? pairIdentity,
    String? side,
  }) {
    final entries = _requestRegistry.takePendingWhere(
      (BleRequestKey key) =>
          (generation == null || key.generation == generation) &&
          (pairIdentity == null || key.pairIdentity == pairIdentity) &&
          (side == null || key.side == side),
""",
    )
    replace_once(
        root,
        relative,
        "pairIdentity: _pairIdentity,\n          errorCode: reason,",
        "pairIdentity: entry.key.pairIdentity,\n          errorCode: reason,",
    )
    replace_once(
        root,
        relative,
        """      generation: _connectionGeneration,
      side: side == 'L' || side == 'R' ? side : null,
""",
        """      generation: _connectionGeneration,
      pairIdentity: _pairIdentity,
      side: side == 'L' || side == 'R' ? side : null,
""",
    )
    replace_once(
        root,
        relative,
        """      generation: retiredGeneration,
    );
""",
        """      generation: retiredGeneration,
      pairIdentity: _pairIdentity,
    );
""",
    )
    replace_once(
        root,
        relative,
        """      generation: _connectionGeneration,
    );
    _pairIdentity = normalizedPair;
""",
        """      generation: _connectionGeneration,
      pairIdentity: _pairIdentity,
    );
    _pairIdentity = normalizedPair;
""",
    )
    replace_once(
        root,
        relative,
        """  @visibleForTesting
  Future<void> handleNativeMethodForTest(MethodCall call) =>
      _methodCallHandler(call);

  @visibleForTesting
  void resetAuthorityForTest() {
""",
        """  @visibleForTesting
  Future<void> handleNativeMethodForTest(MethodCall call) =>
      _methodCallHandler(call);

  @visibleForTesting
  void handleBleResponseForTest(BleReceive response) =>
      _handleReceivedData(response);

  @visibleForTesting
  void resetAuthorityForTest() {
""",
    )


def patch_transport(root: Path) -> None:
    relative = "lib/adapters/even_g1/even_g1_transport.dart"
    replace_once(
        root,
        relative,
        """    final responseGenerationMatches =
        response.generation == 0 || response.generation == identity.generation;
    final responsePairMatches =
        response.pairIdentity == unselectedBlePairIdentity ||
            response.pairIdentity == identity.pairIdentity;
    if (!responseGenerationMatches || !responsePairMatches) {
""",
        """    final responseAuthorityMatches =
        response.hasAuthoritativeIdentity &&
        response.generation == identity.generation &&
        response.pairIdentity == identity.pairIdentity &&
        response.lr == sideCode &&
        response.data.isNotEmpty &&
        response.data.first == bytes.first;
    if (!responseAuthorityMatches) {
""",
    )


def patch_tests(root: Path) -> None:
    write(
        root,
        "test/runtime/ble_receive_test.dart",
        """import 'dart:typed_data';

import 'package:demo_ai_even/services/ble.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('BLE response parses exact connection authority and bytes', () {
    final response = BleReceive.fromMap(<String, Object?>{
      'lr': 'L',
      'data': Uint8List.fromList(<int>[0x25, 0xc9]),
      'type': 'Receive',
      'generation': 7,
      'pairIdentity': 'Pair_45',
    });

    expect(response.lr, 'L');
    expect(response.getCmd(), 0x25);
    expect(response.generation, 7);
    expect(response.pairIdentity, 'Pair_45');
    expect(response.hasAuthoritativeIdentity, isTrue);
    expect(response.isTimeout, isFalse);
  });

  test('BLE command authority rejects missing zero and placeholder identity', () {
    final cases = <Map<String, Object?>>[
      <String, Object?>{'generation': 7},
      <String, Object?>{'generation': 0, 'pairIdentity': 'Pair_45'},
      <String, Object?>{'generation': -1, 'pairIdentity': 'Pair_45'},
      <String, Object?>{'generation': 7, 'pairIdentity': 'unselected'},
      <String, Object?>{'generation': 7, 'pairIdentity': '   '},
      <String, Object?>{'generation': 7, 'pairIdentity': ' Pair_45 '},
    ];

    for (final authority in cases) {
      final response = BleReceive.fromMap(<String, Object?>{
        'lr': 'R',
        'data': Uint8List.fromList(<int>[0x4e, 0xc9]),
        ...authority,
      });
      expect(
        response.hasAuthoritativeIdentity,
        isFalse,
        reason: authority.toString(),
      );
    }
  });

  test('empty BLE response fails closed when command is requested', () {
    final response = BleReceive();
    expect(response.getCmd, throwsStateError);
  });
}
""",
    )

    slot_test = read(root, "test/runtime/ble_request_slot_test.dart")
    slot_test = re.sub(
        r"BleRequestKey\(generation: (\d+), side: '([LR])', command: (0x[0-9a-f]+)\)",
        r"BleRequestKey(generation: \1, pairIdentity: 'Pair_45', side: '\2', command: \3)",
        slot_test,
    )
    slot_test = slot_test.replace(
        "registry.clearQuarantineForGenerationSide(9, 'L');",
        "registry.clearQuarantineForGenerationSide(9, 'Pair_45', 'L');",
    )
    marker = "\n  test('generation replacement clears only the retired namespace', () {"
    pair_test = """

  test('pair identities are independent request and quarantine authorities', () {
    final registry = BleRequestRegistry<int>();
    const pairA = BleRequestKey(
      generation: 11,
      pairIdentity: 'Pair_45',
      side: 'R',
      command: 0x4e,
    );
    const pairB = BleRequestKey(
      generation: 11,
      pairIdentity: 'Pair_91',
      side: 'R',
      command: 0x4e,
    );
    final first = BleRequestSlot<int>(
      completer: Completer<int>(),
      generation: 11,
    );
    final second = BleRequestSlot<int>(
      completer: Completer<int>(),
      generation: 11,
    );

    expect(registry.reserve(pairA, first), isTrue);
    expect(registry.reserve(pairB, second), isTrue);
    expect(registry.quarantineIfOwned(pairA, first), isTrue);
    expect(registry.quarantineIfOwned(pairB, second), isTrue);

    registry.clearQuarantineForGenerationSide(11, 'Pair_45', 'R');

    expect(registry.isQuarantined(pairA), isFalse);
    expect(registry.isQuarantined(pairB), isTrue);
  });
"""
    if marker not in slot_test:
        fail("ble_request_slot_test.dart: insertion marker missing")
    slot_test = slot_test.replace(marker, pair_test + marker, 1)
    write(root, "test/runtime/ble_request_slot_test.dart", slot_test)

    manager_tests = r'''

  Future<BleReceive> requestAndInject({
    required int command,
    required BleReceive response,
    int generation = 41,
    String pairIdentity = 'Pair_45',
  }) async {
    final pending = BleManager.request(
      Uint8List.fromList(<int>[command, 0x01]),
      lr: 'R',
      timeoutMs: 10,
      expectedGeneration: generation,
      expectedPairIdentity: pairIdentity,
    );
    await Future<void>.delayed(Duration.zero);
    manager.handleBleResponseForTest(response);
    return pending;
  }

  test(
    'unscoped and mismatched responses cannot complete or release current authority',
    () async {
      final cases = <({
        String label,
        int command,
        int generation,
        String pairIdentity,
        String side,
      })>[
        (
          label: 'missing generation',
          command: 0x60,
          generation: 0,
          pairIdentity: 'Pair_45',
          side: 'R',
        ),
        (
          label: 'missing pair identity',
          command: 0x61,
          generation: 41,
          pairIdentity: unselectedBlePairIdentity,
          side: 'R',
        ),
        (
          label: 'zero and placeholder identity',
          command: 0x62,
          generation: 0,
          pairIdentity: unselectedBlePairIdentity,
          side: 'R',
        ),
        (
          label: 'stale generation',
          command: 0x63,
          generation: 40,
          pairIdentity: 'Pair_45',
          side: 'R',
        ),
        (
          label: 'wrong pair',
          command: 0x64,
          generation: 41,
          pairIdentity: 'Pair_91',
          side: 'R',
        ),
        (
          label: 'wrong leg',
          command: 0x65,
          generation: 41,
          pairIdentity: 'Pair_45',
          side: 'L',
        ),
      ];

      for (final testCase in cases) {
        final response = BleReceive()
          ..lr = testCase.side
          ..data = Uint8List.fromList(<int>[testCase.command, 0xc9])
          ..generation = testCase.generation
          ..pairIdentity = testCase.pairIdentity;
        final first = await requestAndInject(
          command: testCase.command,
          response: response,
        );
        expect(first.isTimeout, isTrue, reason: testCase.label);
        expect(
          first.errorCode,
          'ack_timeout_after_native_write',
          reason: testCase.label,
        );

        manager.handleBleResponseForTest(response);
        final replay = await BleManager.request(
          Uint8List.fromList(<int>[testCase.command, 0x01]),
          lr: 'R',
          timeoutMs: 10,
          expectedGeneration: 41,
          expectedPairIdentity: 'Pair_45',
        );
        expect(replay.isTimeout, isTrue, reason: testCase.label);
        expect(
          replay.errorCode,
          'request_slot_quarantined',
          reason: testCase.label,
        );
      }
    },
  );

  test('exact response authority completes only the matching request', () async {
    final response = BleReceive()
      ..lr = 'R'
      ..data = Uint8List.fromList(<int>[0x6e, 0xc9])
      ..generation = 41
      ..pairIdentity = 'Pair_45';

    final result = await requestAndInject(command: 0x6e, response: response);

    expect(result.isTimeout, isFalse);
    expect(result.data, Uint8List.fromList(<int>[0x6e, 0xc9]));
    expect(result.hasAuthoritativeIdentity, isTrue);
  });

  test('delayed unscoped response after generation N plus one is rejected',
      () async {
    await manager.handleNativeMethodForTest(
      const MethodCall('glassesConnected', <String, Object>{
        'leftDeviceName': 'G1_45_L_test',
        'rightDeviceName': 'G1_45_R_test',
        'left_connected': true,
        'right_connected': true,
        'generation': 42,
        'pairIdentity': 'Pair_45',
      }),
    );
    final delayed = BleReceive()
      ..lr = 'R'
      ..data = Uint8List.fromList(<int>[0x6f, 0xc9]);

    final first = await requestAndInject(
      command: 0x6f,
      response: delayed,
      generation: 42,
    );
    expect(first.errorCode, 'ack_timeout_after_native_write');

    manager.handleBleResponseForTest(delayed);
    final replay = await BleManager.request(
      Uint8List.fromList(<int>[0x6f, 0x01]),
      lr: 'R',
      timeoutMs: 10,
      expectedGeneration: 42,
      expectedPairIdentity: 'Pair_45',
    );
    expect(replay.errorCode, 'request_slot_quarantined');
  });
'''
    insert_before_last_closing_brace(
        root,
        "test/runtime/ble_manager_authority_test.dart",
        manager_tests,
    )

    transport_tests = r'''

  test('unscoped or mismatched native acknowledgements are indeterminate',
      () async {
    await transport.dispose();
    var invocations = 0;
    final responses = <int, BleReceive>{
      0x70: BleReceive()
        ..lr = 'R'
        ..data = Uint8List.fromList(<int>[0x70, 0xc9])
        ..generation = 0
        ..pairIdentity = 'Pair_45',
      0x71: BleReceive()
        ..lr = 'R'
        ..data = Uint8List.fromList(<int>[0x71, 0xc9])
        ..generation = 7,
      0x72: BleReceive()
        ..lr = 'R'
        ..data = Uint8List.fromList(<int>[0x72, 0xc9])
        ..generation = 6
        ..pairIdentity = 'Pair_45',
      0x73: BleReceive()
        ..lr = 'R'
        ..data = Uint8List.fromList(<int>[0x73, 0xc9])
        ..generation = 7
        ..pairIdentity = 'Pair_91',
      0x74: BleReceive()
        ..lr = 'L'
        ..data = Uint8List.fromList(<int>[0x74, 0xc9])
        ..generation = 7
        ..pairIdentity = 'Pair_45',
      0x75: BleReceive()
        ..lr = 'R'
        ..data = Uint8List.fromList(<int>[0x76, 0xc9])
        ..generation = 7
        ..pairIdentity = 'Pair_45',
    };
    transport = EvenG1Transport(
      manager: source,
      requestSender: (
        Uint8List bytes, {
        required String lr,
        required int timeoutMs,
        required int expectedGeneration,
        required String expectedPairIdentity,
      }) async {
        invocations++;
        return responses[bytes.first]!;
      },
    );

    for (final command in responses.keys) {
      final result = await transport.send(
        side: GlassesSide.right,
        bytes: Uint8List.fromList(<int>[command, 0x01]),
        timeout: const Duration(milliseconds: 200),
        idempotencyKey: 'authority-$command',
      );
      expect(result.accepted, isFalse, reason: '$command');
      expect(result.requiresReconciliation, isTrue, reason: '$command');
      expect(result.effectMayHaveOccurred, isTrue, reason: '$command');
      expect(
        result.errorCode,
        'native_response_authority_mismatch',
        reason: '$command',
      );
    }

    final replay = await transport.send(
      side: GlassesSide.right,
      bytes: Uint8List.fromList(<int>[0x70, 0x01]),
      timeout: const Duration(milliseconds: 200),
      idempotencyKey: 'authority-112',
    );
    expect(replay.errorCode, 'native_response_authority_mismatch');
    expect(invocations, responses.length);
  });
'''
    insert_before_last_closing_brace(
        root,
        "test/runtime/even_g1_transport_authority_test.dart",
        transport_tests,
    )


def patch_contract_and_truth(root: Path) -> None:
    relative = "contracts/g1-ble-protocol-v1.json"
    contract = json.loads(read(root, relative))
    authority = contract.get("authority")
    if not isinstance(authority, dict):
        fail("G1 BLE contract has no authority object")
    authority["response_identity"] = {
        "required": [
            "pair_identity",
            "connection_generation",
            "side",
            "command",
        ],
        "missing_or_placeholder": "reject_before_pending_or_quarantine_mutation",
        "mismatch": "reject_before_pending_or_quarantine_mutation",
        "legacy_unscoped": "telemetry_only_non_authoritative",
    }
    quarantine = authority.get("uncertain_write_quarantine")
    if not isinstance(quarantine, dict):
        fail("G1 BLE contract has no quarantine object")
    quarantine["identity"] = [
        "pair_identity",
        "connection_generation",
        "side",
        "command",
    ]
    contract["version"] = 3
    write(root, relative, json.dumps(contract, ensure_ascii=False, indent=2) + "\n")

    ledger_relative = "docs/GAP_LEDGER.yaml"
    ledger = json.loads(read(root, ledger_relative))
    gaps = ledger.get("gaps")
    if not isinstance(gaps, list):
        fail("Gap Ledger has no gaps array")
    if any(gap.get("id") == "HG-0065" for gap in gaps if isinstance(gap, dict)):
        fail("HG-0065 already exists")
    gaps.append(
        {
            "id": "HG-0065",
            "title": "Unscoped native BLE responses could be promoted to current request authority",
            "owner": "device-runtime",
            "status": "CLOSED_SOURCE",
            "evidence": [
                "contracts/g1-ble-protocol-v1.json",
                "lib/services/ble.dart",
                "lib/runtime/ble_request_slot.dart",
                "lib/ble_manager.dart",
                "lib/adapters/even_g1/even_g1_transport.dart",
                "test/runtime/ble_receive_test.dart",
                "test/runtime/ble_request_slot_test.dart",
                "test/runtime/ble_manager_authority_test.dart",
                "test/runtime/even_g1_transport_authority_test.dart",
            ],
        }
    )
    write(
        root,
        ledger_relative,
        json.dumps(ledger, ensure_ascii=False, separators=(",", ":")) + "\n",
    )

    document = read(root, "docs/development/G8_SOURCE_REMEDIATION.md")
    section = """

### Exact native response authority (`HG-0065`)

- command, acknowledgement, and touch/assistant responses now require a positive connection generation, a non-placeholder exact pair identity, an exact side, and the request command before they can touch a pending owner or uncertain-write quarantine;
- missing, zero, placeholder, stale, wrong-pair, wrong-leg, and wrong-command responses are rejected before current request authority is consumed;
- request and quarantine identity now includes pair identity in addition to connection generation, side, and command;
- the public transport treats any unscoped or mismatched post-write response as indeterminate, caches that receipt, and requires reconciliation rather than accepting or blindly retrying it;
- hostile tests cover delayed unscoped responses after generation replacement and prove that current slots and quarantine remain unchanged.
"""
    if "Exact native response authority (`HG-0065`)" in document:
        fail("G8 response-authority section already exists")
    write(root, "docs/development/G8_SOURCE_REMEDIATION.md", document.rstrip() + section + "\n")


def patch_validator(root: Path) -> None:
    relative = "tools/validate_repository.py"
    replace_once(
        root,
        relative,
        '    "test/runtime/ble_request_slot_test.dart",\n',
        '    "test/runtime/ble_request_slot_test.dart",\n'
        '    "test/runtime/ble_receive_test.dart",\n',
    )
    replace_once(
        root,
        relative,
        "if not isinstance(gaps, list) or len(gaps) < 57:",
        "if not isinstance(gaps, list) or len(gaps) < 65:",
    )
    replace_once(
        root,
        relative,
        '"HG-0063", "HG-0064"):',
        '"HG-0063", "HG-0064", "HG-0065"):',
    )
    replace_once(
        root,
        relative,
        """    manager = (ROOT / "lib/ble_manager.dart").read_text(encoding="utf-8")
    slots = (ROOT / "lib/runtime/ble_request_slot.dart").read_text(
""",
        """    manager = (ROOT / "lib/ble_manager.dart").read_text(encoding="utf-8")
    responses = (ROOT / "lib/services/ble.dart").read_text(encoding="utf-8")
    slots = (ROOT / "lib/runtime/ble_request_slot.dart").read_text(
""",
    )
    replace_once(
        root,
        relative,
        """    manager_test = (
        ROOT / "test/runtime/ble_manager_authority_test.dart"
    ).read_text(encoding="utf-8")
    ios_test = (ROOT / "ios/RunnerTests/RunnerTests.swift").read_text(
""",
        """    manager_test = (
        ROOT / "test/runtime/ble_manager_authority_test.dart"
    ).read_text(encoding="utf-8")
    response_test = (ROOT / "test/runtime/ble_receive_test.dart").read_text(
        encoding="utf-8"
    )
    slot_test = (ROOT / "test/runtime/ble_request_slot_test.dart").read_text(
        encoding="utf-8"
    )
    ios_test = (ROOT / "ios/RunnerTests/RunnerTests.swift").read_text(
""",
    )
    replace_once(
        root,
        relative,
        """    if any(fragment not in transport for fragment in transport_fragments):
        fail("public BLE transport does not bind complete idempotency authority")

    manager_fragments = (
""",
        """    if any(fragment not in transport for fragment in transport_fragments):
        fail("public BLE transport does not bind complete idempotency authority")
    response_fragments = (
        "hasAuthoritativeIdentity",
        "generation > 0",
        "normalizedPairIdentity != unselectedBlePairIdentity",
    )
    if any(fragment not in responses for fragment in response_fragments):
        fail("BLE response parsing does not fail closed on missing authority")
    transport_forbidden = (
        "response.generation == 0 ||",
        "response.pairIdentity == unselectedBlePairIdentity ||",
    )
    if any(fragment in transport for fragment in transport_forbidden):
        fail("public BLE transport still accepts wildcard response authority")
    if (
        "response.lr == sideCode" not in transport
        or "response.data.first == bytes.first" not in transport
    ):
        fail("public BLE transport does not verify response side and command")

    manager_fragments = (
""",
    )
    replace_once(
        root,
        relative,
        """        "expected_pair_mismatch_before_write",
        "request_slot_quarantined",
    )
""",
        """        "expected_pair_mismatch_before_write",
        "connection_authority_unavailable",
        "request_slot_quarantined",
        "ble_unscoped_response_rejected",
        "pairIdentity: response.pairIdentity",
    )
""",
    )
    replace_once(
        root,
        relative,
        """    if any(fragment not in manager for fragment in manager_fragments):
        fail("Flutter BLE request authority or scoped quarantine drifted")
    disconnect_section = manager.split("void _onGlassesDisconnected", 1)[1].split(
""",
        """    if any(fragment not in manager for fragment in manager_fragments):
        fail("Flutter BLE request authority or scoped quarantine drifted")
    manager_forbidden = (
        "response.generation > 0 ? response.generation : _connectionGeneration",
        "pending.generation == generation || pending.generation == 0",
    )
    if any(fragment in manager for fragment in manager_forbidden):
        fail("Flutter BLE response path still promotes unscoped authority")
    disconnect_section = manager.split("void _onGlassesDisconnected", 1)[1].split(
""",
    )
    replace_once(
        root,
        relative,
        """    if "left disconnect cannot release an uncertain right-leg write" not in manager_test:
        fail("one-leg disconnect quarantine regression is missing")
    if "testGenerationNTokenCannotOwnGenerationNPlusOne" not in ios_test:
""",
        """    if "left disconnect cannot release an uncertain right-leg write" not in manager_test:
        fail("one-leg disconnect quarantine regression is missing")
    if (
        "unscoped and mismatched responses cannot complete or release current authority"
        not in manager_test
        or "delayed unscoped response after generation N plus one is rejected"
        not in manager_test
    ):
        fail("hostile unscoped BLE response regressions are missing")
    if (
        "unscoped or mismatched native acknowledgements are indeterminate"
        not in transport_test
    ):
        fail("transport response-authority regression is missing")
    if "BLE command authority rejects missing zero and placeholder identity" not in response_test:
        fail("BLE response parser authority regression is missing")
    if "pair identities are independent request and quarantine authorities" not in slot_test:
        fail("pair-scoped BLE request registry regression is missing")
    if "testGenerationNTokenCannotOwnGenerationNPlusOne" not in ios_test:
""",
    )
    replace_once(
        root,
        relative,
        """    if protocol.get("version", 0) < 2 or not isinstance(authority, dict):
        fail("machine-readable BLE authority contract is missing")
""",
        """    if protocol.get("version", 0) < 3 or not isinstance(authority, dict):
        fail("machine-readable BLE authority contract is missing")
""",
    )
    replace_once(
        root,
        relative,
        """    quarantine = authority.get("uncertain_write_quarantine", {})
    if quarantine.get("opposite_leg_disconnect_releases") is not False:
        fail("BLE contract permits opposite-leg quarantine release")
""",
        """    response_identity = authority.get("response_identity", {})
    required_response_identity = {
        "pair_identity",
        "connection_generation",
        "side",
        "command",
    }
    if set(response_identity.get("required", [])) != required_response_identity:
        fail("machine-readable BLE response identity drifted")
    if (
        response_identity.get("missing_or_placeholder")
        != "reject_before_pending_or_quarantine_mutation"
    ):
        fail("BLE contract permits unscoped response authority")
    quarantine = authority.get("uncertain_write_quarantine", {})
    if set(quarantine.get("identity", [])) != required_response_identity:
        fail("BLE quarantine identity is not pair scoped")
    if quarantine.get("opposite_leg_disconnect_releases") is not False:
        fail("BLE contract permits opposite-leg quarantine release")
""",
    )


def main() -> int:
    if len(sys.argv) != 2:
        fail("usage: apply_response_authority.py REPOSITORY_ROOT")
    root = Path(sys.argv[1]).resolve()
    patch_ble_receive(root)
    patch_request_registry(root)
    patch_ble_manager(root)
    patch_transport(root)
    patch_tests(root)
    patch_contract_and_truth(root)
    patch_validator(root)
    print("G8 exact native response authority remediation applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
