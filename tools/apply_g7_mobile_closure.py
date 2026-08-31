#!/usr/bin/env python3
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
G4_HEAD = "957d9388040904be1e1d3219d7ed9f46e375f7ff"


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def copy_from(ref: str, path: str) -> None:
    write(path, subprocess.check_output(["git", "show", f"{ref}:{path}"], cwd=ROOT, text=True))


def bitmap_source() -> str:
    return r'''import 'dart:async';
import 'dart:io';
import 'dart:math';
import 'dart:typed_data';

import 'package:crclib/catalog.dart';
import 'package:demo_ai_even/ble_manager.dart';
import 'package:demo_ai_even/runtime/privacy_safe_log.dart';
import 'package:demo_ai_even/utils/utils.dart';

final class BmpTransferCodec {
  const BmpTransferCodec._();

  static const int packetPayloadBytes = 194;
  static const int maximumPacketCount = 256;
  static const int maximumImageBytes = packetPayloadBytes * maximumPacketCount;
  static const List<int> storageAddress = <int>[0x00, 0x1c, 0x00, 0x00];

  static List<Uint8List> buildPackets(Uint8List image) {
    if (image.isEmpty || image.length > maximumImageBytes) {
      throw ArgumentError.value(image.length, 'image', 'BMP payload must be between 1 and $maximumImageBytes bytes');
    }
    final packets = <Uint8List>[];
    for (var offset = 0; offset < image.length; offset += packetPayloadBytes) {
      final end = min(offset + packetPayloadBytes, image.length);
      final sequence = packets.length;
      if (sequence >= maximumPacketCount) {
        throw StateError('BMP packet sequence exceeds one-byte protocol range.');
      }
      final payload = image.sublist(offset, end);
      final prefix = sequence == 0 ? <int>[0x15, sequence, ...storageAddress] : <int>[0x15, sequence];
      packets.add(Utils.addPrefixToUint8List(prefix, payload));
    }
    return List<Uint8List>.unmodifiable(packets);
  }

  static Uint8List crcPayload(Uint8List image) => Utils.addPrefixToUint8List(storageAddress, image);

  static int? responseStatus(Uint8List response) {
    if (response.length > 5 && response.first == 0x16) {
      return response[5];
    }
    return response.length > 1 ? response[1] : null;
  }

  static bool isSuccessResponse(Uint8List response) {
    final status = responseStatus(response);
    return status == 0xc9 || status == 0xcb;
  }
}

class BmpUpdateManager {
  static bool isTransfering = false;
  static final Set<String> _activeSides = <String>{};

  Future<bool> updateBmp(String lr, Uint8List image, {int? seq}) async {
    if (lr != 'L' && lr != 'R') {
      throw ArgumentError.value(lr, 'lr', 'must be L or R');
    }
    if (_activeSides.contains(lr)) {
      PrivacySafeLog.event('bmp_transfer_rejected', fields: <String, Object?>{'side': lr, 'reason': 'already_running'});
      return false;
    }
    final List<Uint8List> packets;
    try {
      packets = BmpTransferCodec.buildPackets(image);
    } on Object catch (error) {
      PrivacySafeLog.event('bmp_transfer_rejected', fields: <String, Object?>{'side': lr, 'reason': 'invalid_payload', 'error_type': error.runtimeType.toString()});
      return false;
    }
    final startSequence = seq ?? 0;
    if (startSequence < 0 || startSequence >= packets.length) {
      return false;
    }
    _activeSides.add(lr);
    isTransfering = true;
    try {
      PrivacySafeLog.event('bmp_transfer_started', fields: <String, Object?>{'side': lr, 'bytes': image.length, 'packets': packets.length, 'start_sequence': startSequence});
      for (var index = startSequence; index < packets.length; index++) {
        final queued = await BleManager.sendData(packets[index], lr: lr);
        if (queued == false) {
          PrivacySafeLog.event('bmp_packet_rejected', fields: <String, Object?>{'side': lr, 'sequence': index});
          return false;
        }
        await Future<void>.delayed(Duration(milliseconds: Platform.isIOS ? 8 : 5));
      }
      final finish = await BleManager.request(Uint8List.fromList(<int>[0x20, 0x0d, 0x0e]), lr: lr, timeoutMs: 3000);
      if (finish.isTimeout || !BmpTransferCodec.isSuccessResponse(finish.data)) {
        PrivacySafeLog.event('bmp_finish_unacknowledged', fields: <String, Object?>{'side': lr, 'effect_may_have_occurred': finish.effectMayHaveOccurred});
        return false;
      }
      final checksum = Crc32Xz().convert(BmpTransferCodec.crcPayload(image)).toBigInt().toInt();
      final crc = Uint8List.fromList(<int>[checksum >> 24 & 0xff, checksum >> 16 & 0xff, checksum >> 8 & 0xff, checksum & 0xff]);
      final checked = await BleManager.request(Utils.addPrefixToUint8List(<int>[0x16], crc), lr: lr, timeoutMs: 3000);
      final success = !checked.isTimeout && BmpTransferCodec.isSuccessResponse(checked.data);
      PrivacySafeLog.event(success ? 'bmp_transfer_completed' : 'bmp_crc_unacknowledged', fields: <String, Object?>{'side': lr, 'bytes': image.length, 'packets': packets.length, if (!success) 'effect_may_have_occurred': checked.effectMayHaveOccurred});
      return success;
    } on TimeoutException {
      PrivacySafeLog.event('bmp_transfer_timeout', fields: <String, Object?>{'side': lr});
      return false;
    } on Object catch (error) {
      PrivacySafeLog.event('bmp_transfer_failed', fields: <String, Object?>{'side': lr, 'error_type': error.runtimeType.toString()});
      return false;
    } finally {
      _activeSides.remove(lr);
      isTransfering = _activeSides.isNotEmpty;
    }
  }
}
'''


def history_ui_source() -> str:
    return r'''import 'package:demo_ai_even/controllers/evenai_model_controller.dart';
import 'package:demo_ai_even/services/evenai.dart';
import 'package:flutter/material.dart';
import 'package:get/get.dart';

class EvenAIListPage extends StatelessWidget {
  const EvenAIListPage({super.key});

  @override
  Widget build(BuildContext context) {
    final controller = Get.find<EvenaiModelController>();
    return Scaffold(
      appBar: AppBar(title: const Text('History', style: TextStyle(fontSize: 20))),
      body: Obx(() {
        if (controller.items.isEmpty && !EvenAI.isEvenAISyncing.value) {
          return const Center(child: Padding(padding: EdgeInsets.all(24), child: Text('Press and hold left TouchBar to engage Even AI.', style: TextStyle(color: Colors.grey), textAlign: TextAlign.center)));
        }
        return ListView.builder(
          padding: const EdgeInsets.fromLTRB(16, 4, 16, 16),
          itemCount: controller.items.length,
          itemBuilder: (BuildContext context, int index) {
            final item = controller.items[index];
            final expanded = controller.selectedIndex.value == index;
            return Card(
              key: ValueKey<String>('history-${item.createdTime.microsecondsSinceEpoch}-$index'),
              margin: const EdgeInsets.symmetric(vertical: 8),
              color: const Color(0x33FEF991),
              clipBehavior: Clip.antiAlias,
              child: Semantics(
                button: true,
                label: item.title,
                child: InkWell(
                  onTap: () => expanded ? controller.deselectItem() : controller.selectItem(index),
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: <Widget>[
                      Text(item.title, style: Theme.of(context).textTheme.titleLarge),
                      if (expanded) ...<Widget>[const SizedBox(height: 12), Text(item.content, style: Theme.of(context).textTheme.bodyMedium)],
                    ]),
                  ),
                ),
              ),
            );
          },
        );
      }),
    );
  }
}
'''


def scheduler_source() -> str:
    return r'''import 'dart:async';
import 'dart:collection';

final class _ScheduledEffect {
  const _ScheduledEffect(this.run);
  final Future<void> Function() run;
}

final class DeviceEffectScheduler {
  DeviceEffectScheduler({this.maxPending = 64}) {
    if (maxPending < 1) {
      throw ArgumentError.value(maxPending, 'maxPending', 'must be positive');
    }
  }

  final int maxPending;
  final Queue<_ScheduledEffect> _queue = Queue<_ScheduledEffect>();
  bool _draining = false;
  bool _closed = false;
  Completer<void>? _idle;

  int get pending => _queue.length + (_draining ? 1 : 0);

  Future<T> schedule<T>(String operation, Future<T> Function() effect) {
    if (operation.trim().isEmpty) {
      throw ArgumentError.value(operation, 'operation', 'must not be empty');
    }
    if (_closed) {
      return Future<T>.error(StateError('Device effect scheduler is closed.'));
    }
    if (pending >= maxPending) {
      return Future<T>.error(StateError('Device effect scheduler capacity exceeded.'));
    }
    _idle ??= Completer<void>();
    final completer = Completer<T>();
    _queue.add(_ScheduledEffect(() async {
      try {
        completer.complete(await effect());
      } on Object catch (error, stackTrace) {
        completer.completeError(error, stackTrace);
      }
    }));
    unawaited(_drain());
    return completer.future;
  }

  Future<void> close({Duration timeout = const Duration(seconds: 30)}) async {
    if (timeout <= Duration.zero) {
      throw ArgumentError.value(timeout, 'timeout', 'must be positive');
    }
    _closed = true;
    final idle = _idle;
    if (idle != null && !idle.isCompleted) {
      await idle.future.timeout(timeout, onTimeout: () => throw TimeoutException('Device effect scheduler did not become idle.', timeout));
    }
  }

  Future<void> _drain() async {
    if (_draining) return;
    _draining = true;
    try {
      while (_queue.isNotEmpty) {
        await _queue.removeFirst().run();
      }
    } finally {
      _draining = false;
      if (_queue.isNotEmpty) {
        unawaited(_drain());
      } else {
        final idle = _idle;
        _idle = null;
        if (idle != null && !idle.isCompleted) idle.complete();
      }
    }
  }
}
'''


def bitmap_test() -> str:
    return r'''import 'dart:typed_data';

import 'package:demo_ai_even/controllers/bmp_update_manager.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('BMP packets preserve payload and one-byte sequence bounds', () {
    final payload = Uint8List.fromList(List<int>.generate(400, (int index) => index & 0xff));
    final packets = BmpTransferCodec.buildPackets(payload);
    expect(packets, hasLength(3));
    expect(packets.first.sublist(0, 6), <int>[0x15, 0, 0, 0x1c, 0, 0]);
    expect(packets[1].sublist(0, 2), <int>[0x15, 1]);
    final rebuilt = <int>[...packets.first.sublist(6), ...packets[1].sublist(2), ...packets[2].sublist(2)];
    expect(rebuilt, payload);
  });

  test('BMP codec rejects empty and oversized payloads', () {
    expect(() => BmpTransferCodec.buildPackets(Uint8List(0)), throwsArgumentError);
    expect(() => BmpTransferCodec.buildPackets(Uint8List(BmpTransferCodec.maximumImageBytes + 1)), throwsArgumentError);
  });

  test('BMP response parsing fails closed on short responses', () {
    expect(BmpTransferCodec.responseStatus(Uint8List(0)), isNull);
    expect(BmpTransferCodec.responseStatus(Uint8List.fromList(<int>[0x16])), isNull);
    expect(BmpTransferCodec.isSuccessResponse(Uint8List.fromList(<int>[0x20, 0xc9])), isTrue);
    expect(BmpTransferCodec.isSuccessResponse(Uint8List.fromList(<int>[0x16, 0, 0, 0, 0, 0xc9])), isTrue);
    expect(BmpTransferCodec.isSuccessResponse(Uint8List.fromList(<int>[0x16, 0, 0, 0, 0])), isFalse);
  });
}
'''


def history_ui_test() -> str:
    return r'''import 'package:demo_ai_even/controllers/evenai_model_controller.dart';
import 'package:demo_ai_even/services/evenai.dart';
import 'package:demo_ai_even/views/even_list_page.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:get/get.dart';

void main() {
  setUp(() {
    Get.testMode = true;
    Get.put(EvenaiModelController());
    EvenAI.isEvenAISyncing.value = false;
  });
  tearDown(() async {
    await Get.deleteAll(force: true);
    EvenAI.isEvenAISyncing.value = false;
  });
  testWidgets('history list renders and expands without parent-data errors', (WidgetTester tester) async {
    Get.find<EvenaiModelController>().addItem('Question', 'Answer');
    await tester.pumpWidget(const MaterialApp(home: EvenAIListPage()));
    await tester.pump();
    expect(find.text('Question'), findsOneWidget);
    expect(find.text('Answer'), findsNothing);
    expect(tester.takeException(), isNull);
    await tester.tap(find.text('Question'));
    await tester.pump();
    expect(find.text('Answer'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
'''


def scheduler_test() -> str:
    return r'''import 'dart:async';

import 'package:demo_ai_even/runtime/device_effect_scheduler.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('close completes when the queued effect becomes idle', () async {
    final scheduler = DeviceEffectScheduler();
    final release = Completer<void>();
    final effect = scheduler.schedule<void>('wait', () => release.future);
    final closing = scheduler.close(timeout: const Duration(seconds: 1));
    release.complete();
    await effect;
    await closing;
  });
  test('close has a bounded timeout for a stuck physical effect', () async {
    final scheduler = DeviceEffectScheduler();
    final never = Completer<void>();
    unawaited(scheduler.schedule<void>('stuck', () => never.future));
    await expectLater(scheduler.close(timeout: const Duration(milliseconds: 10)), throwsA(isA<TimeoutException>()));
    never.complete();
  });
}
'''


def main() -> int:
    copy_from(G4_HEAD, 'lib/main.dart')
    copy_from(G4_HEAD, 'lib/runtime/audit_journal.dart')
    copy_from(G4_HEAD, 'test/runtime/audit_journal_test.dart')
    write('lib/controllers/bmp_update_manager.dart', bitmap_source())
    write('lib/views/even_list_page.dart', history_ui_source())
    write('lib/runtime/device_effect_scheduler.dart', scheduler_source())
    write('test/runtime/bmp_transfer_codec_test.dart', bitmap_test())
    write('test/runtime/even_ai_list_page_test.dart', history_ui_test())
    write('test/runtime/device_effect_scheduler_close_test.dart', scheduler_test())

    ble_path = ROOT / 'lib/ble_manager.dart'
    ble = ble_path.read_text(encoding='utf-8')
    if 'bool _heartbeatInFlight' not in ble:
        ble = ble.replace('Timer? beatHeartTimer;', 'Timer? beatHeartTimer;\n  bool _heartbeatInFlight = false;')
    ble = ble.replace("isLeftConnected = values['left_connected'] != false;", "isLeftConnected = values['left_connected'] == true;")
    ble = ble.replace("isRightConnected = values['right_connected'] != false;", "isRightConnected = values['right_connected'] == true;")
    old = '''    beatHeartTimer = Timer.periodic(const Duration(seconds: 8), (_) async {
      if (!isConnected) {
        return;
      }
      final success = await Proto.sendHeartBeat();
      if (!success && tryTime < 2) {
        tryTime++;
        await Proto.sendHeartBeat();
      } else {
        tryTime = 0;
      }
    });
'''
    new = '''    beatHeartTimer = Timer.periodic(const Duration(seconds: 8), (_) async {
      if (!isConnected || _heartbeatInFlight) {
        return;
      }
      _heartbeatInFlight = true;
      try {
        final success = await Proto.sendHeartBeat();
        if (!success && tryTime < 2 && isConnected) {
          tryTime++;
          await Proto.sendHeartBeat();
        } else {
          tryTime = 0;
        }
      } finally {
        _heartbeatInFlight = false;
      }
    });
'''
    if old in ble:
        ble = ble.replace(old, new)
    ble_path.write_text(ble, encoding='utf-8')

    even_path = ROOT / 'lib/services/evenai.dart'
    even = even_path.read_text(encoding='utf-8')
    even = even.replace("  void startListening(AssistantSessionToken session) {\n    combinedText = '';\n    _finalTranscript = Completer<String>();\n    unawaited(_speechSubscription?.cancel());", "  Future<void> startListening(AssistantSessionToken session) async {\n    combinedText = '';\n    _finalTranscript = Completer<String>();\n    await _speechSubscription?.cancel();")
    even = even.replace('    startListening(session);\n', '    await startListening(session);\n')
    even_path.write_text(even, encoding='utf-8')

    text_path = ROOT / 'lib/views/features/text_page.dart'
    text = text_path.read_text(encoding='utf-8').replace('!BleManager.get().isConnected && tfController.text.isNotEmpty', '!BleManager.get().isConnected || tfController.text.isEmpty')
    if 'tfController.dispose();' not in text:
        text = text.replace('\n  @override\n  Widget build', '\n  @override\n  void dispose() {\n    tfController.dispose();\n    super.dispose();\n  }\n\n  @override\n  Widget build', 1)
    text_path.write_text(text, encoding='utf-8')

    notify_path = ROOT / 'lib/views/features/notification/notification_page.dart'
    notify = notify_path.read_text(encoding='utf-8')
    if 'identifierCtl.dispose();' not in notify:
        notify = notify.replace('\n  @override\n  Widget build', '\n  @override\n  void dispose() {\n    identifierFn.dispose();\n    contentFn.dispose();\n    identifierCtl.dispose();\n    contentCtl.dispose();\n    super.dispose();\n  }\n\n  @override\n  Widget build', 1)
    notify_path.write_text(notify, encoding='utf-8')

    pair_path = ROOT / 'android/app/src/main/kotlin/com/example/demo_ai_even/model/BlePairDevice.kt'
    pair = pair_path.read_text(encoding='utf-8')
    if '"left_connected"' not in pair:
        pair = pair.replace('"status" to "connected"', '"status" to "connected",\n        "left_connected" to (leftDevice?.isConnect == true),\n        "right_connected" to (rightDevice?.isConnect == true)')
    pair_path.write_text(pair, encoding='utf-8')

    swift_path = ROOT / 'ios/Runner/BluetoothManager.swift'
    swift = swift_path.read_text(encoding='utf-8')
    if 'reconnectSuppressed' not in swift:
        swift = swift.replace('var currentConnectingDeviceName: String?', 'var reconnectSuppressed = false\n    var currentConnectingDeviceName: String?', 1)
    swift = swift.replace('    func connectToDevice(deviceName: String, result: @escaping FlutterResult) {\n', '    func connectToDevice(deviceName: String, result: @escaping FlutterResult) {\n        reconnectSuppressed = false\n', 1)
    swift = swift.replace('    func disconnectFromGlasses(result: @escaping FlutterResult) {\n', '    func disconnectFromGlasses(result: @escaping FlutterResult) {\n        reconnectSuppressed = true\n', 1)
    swift = swift.replace('        central.connect(peripheral, options: nil)\n', '        if !reconnectSuppressed {\n            central.connect(peripheral, options: nil)\n        }\n')
    if '"left_connected"' not in swift:
        swift = swift.replace('let connectedInfo: [String: String] = [', 'let connectedInfo: [String: Any] = [')
        swift = swift.replace('"status": "connected"\n', '"status": "connected",\n                "left_connected": true,\n                "right_connected": true\n', 1)
    swift_path.write_text(swift, encoding='utf-8')

    Path(__file__).unlink()
    for name in ['g7-mobile-materialize.yml', 'g7-p0-materialize.yml', 'g7-p0-converge.yml']:
        path = ROOT / '.github/workflows' / name
        if path.exists():
            path.unlink()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
