import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';

import 'package:demo_ai_even/ble_manager.dart';
import 'package:demo_ai_even/runtime/privacy_safe_log.dart';
import 'package:demo_ai_even/services/ble.dart';
import 'package:demo_ai_even/services/evenai_proto.dart';
import 'package:demo_ai_even/utils/utils.dart';

class Proto {
  Proto._();

  static String lR() => BleManager.isBothConnected() ? 'R' : 'L';

  static Future<(int, bool)> micOn({String? lr}) async {
    final begin = Utils.getTimestampMs();
    final data = Uint8List.fromList(<int>[0x0E, 0x01]);
    final receive = await BleManager.request(data, lr: lr);
    final end = Utils.getTimestampMs();
    final startMic = begin + ((end - begin) ~/ 2);
    final success = !receive.isTimeout && _isAck(receive.data);
    PrivacySafeLog.event(
      'microphone_command_completed',
      fields: <String, Object?>{'success': success},
    );
    return (startMic, success);
  }

  static int _evenAiSequence = 0;

  static Future<bool> sendEvenAIData(
    String text, {
    int? timeoutMs,
    required int newScreen,
    required int pos,
    int? currentPageNumber,
    int? maxPageNumber,
    // ignore: non_constant_identifier_names
    int? current_page_num,
    // ignore: non_constant_identifier_names
    int? max_page_num,
  }) async {
    final currentPage = currentPageNumber ?? current_page_num;
    final maximumPage = maxPageNumber ?? max_page_num;
    if (currentPage == null || maximumPage == null) {
      throw ArgumentError(
        'Both current and maximum page numbers must be provided.',
      );
    }

    final encoded = utf8.encode(text);
    final syncSequence = _evenAiSequence & 0xff;
    final packets = EvenaiProto.evenaiMultiPackListV2(
      0x4E,
      data: encoded,
      syncSeq: syncSequence,
      newScreen: newScreen,
      pos: pos,
      current_page_num: currentPage,
      max_page_num: maximumPage,
    );
    _evenAiSequence = (_evenAiSequence + 1) & 0xff;
    if (packets.isEmpty) {
      return false;
    }

    final left = await BleManager.requestList(
      packets,
      lr: 'L',
      timeoutMs: timeoutMs ?? 2000,
    );
    if (!left) {
      PrivacySafeLog.event(
        'display_packet_batch_failed',
        fields: <String, Object?>{'side': 'left', 'packets': packets.length},
      );
      return false;
    }
    final right = await BleManager.requestList(
      packets,
      lr: 'R',
      timeoutMs: timeoutMs ?? 2000,
    );
    if (!right) {
      PrivacySafeLog.event(
        'display_packet_batch_failed',
        fields: <String, Object?>{'side': 'right', 'packets': packets.length},
      );
    }
    return right;
  }

  static int _heartbeatSequence = 0;

  static Future<bool> sendHeartBeat() async {
    const length = 6;
    final sequence = _heartbeatSequence & 0xff;
    final data = Uint8List.fromList(<int>[
      0x25,
      length & 0xff,
      (length >> 8) & 0xff,
      sequence,
      0x04,
      sequence,
    ]);
    _heartbeatSequence = (_heartbeatSequence + 1) & 0xff;

    final left = await BleManager.request(data, lr: 'L', timeoutMs: 1500);
    if (!_isHeartbeatAck(left)) {
      return false;
    }
    final right = await BleManager.request(data, lr: 'R', timeoutMs: 1500);
    return _isHeartbeatAck(right);
  }

  static bool _isHeartbeatAck(BleReceive response) =>
      !response.isTimeout &&
      response.data.length > 5 &&
      response.data[0] == 0x25 &&
      response.data[4] == 0x04;

  static bool _isAck(Uint8List data) =>
      data.length > 1 && (data[1] == 0xc9 || data[1] == 0xcb);

  static Future<String> getLegSn(String lr) async {
    final response = await BleManager.request(
      Uint8List.fromList(<int>[0x34]),
      lr: lr,
    );
    if (response.isTimeout || response.data.length < 18) {
      throw StateError('Serial-number response was incomplete.');
    }
    return String.fromCharCodes(response.data.sublist(2, 18));
  }

  static Future<bool> exit() async {
    final data = Uint8List.fromList(<int>[0x18]);
    final left = await BleManager.request(data, lr: 'L', timeoutMs: 1500);
    if (left.isTimeout || !_isAck(left.data)) {
      return false;
    }
    final right = await BleManager.request(data, lr: 'R', timeoutMs: 1500);
    return !right.isTimeout && _isAck(right.data);
  }

  static List<Uint8List> _getPackList(
    int command,
    Uint8List data, {
    int count = 20,
  }) {
    if (count <= 3) {
      throw ArgumentError.value(count, 'count', 'must exceed header size');
    }
    final payloadBytes = count - 3;
    final packetCount = max(1, (data.length + payloadBytes - 1) ~/ payloadBytes);
    if (packetCount > 255) {
      throw StateError('Payload exceeds protocol packet limit.');
    }
    final packets = <Uint8List>[];
    for (var sequence = 0; sequence < packetCount; sequence++) {
      final start = sequence * payloadBytes;
      final end = start + payloadBytes < data.length
          ? start + payloadBytes
          : data.length;
      final itemData = start < data.length
          ? data.sublist(start, end)
          : Uint8List(0);
      packets.add(
        Utils.addPrefixToUint8List(
          <int>[command, packetCount, sequence],
          itemData,
        ),
      );
    }
    return packets;
  }

  static Future<bool> sendNewAppWhiteListJson(String whitelistJson) async {
    final packets = _getPackList(
      0x04,
      Uint8List.fromList(utf8.encode(whitelistJson)),
      count: 180,
    );
    final success =
        await BleManager.requestList(packets, timeoutMs: 300, lr: 'L');
    if (!success) {
      PrivacySafeLog.event(
        'whitelist_send_failed',
        fields: <String, Object?>{'packets': packets.length},
      );
    }
    return success;
  }

  static Future<bool> sendNotify(
    Map<Object?, Object?> appData,
    int notifyId, {
    int retry = 0,
  }) async {
    final notifyJson = jsonEncode(<String, Object?>{
      'ncs_notification': appData,
    });
    final packets = _getNotifyPackList(
      0x4B,
      notifyId,
      Uint8List.fromList(utf8.encode(notifyJson)),
    );
    final success =
        await BleManager.requestList(packets, timeoutMs: 1000, lr: 'L');
    if (!success) {
      PrivacySafeLog.event(
        'notification_send_failed',
        fields: <String, Object?>{
          'notification_id': notifyId,
          'packets': packets.length,
        },
      );
    }
    return success;
  }

  static List<Uint8List> _getNotifyPackList(
    int command,
    int messageId,
    Uint8List data,
  ) {
    const payloadBytes = 176;
    final packetCount = max(1, (data.length + payloadBytes - 1) ~/ payloadBytes);
    if (packetCount > 255) {
      throw StateError('Notification exceeds protocol packet limit.');
    }
    final packets = <Uint8List>[];
    for (var sequence = 0; sequence < packetCount; sequence++) {
      final start = sequence * payloadBytes;
      final end = start + payloadBytes < data.length
          ? start + payloadBytes
          : data.length;
      final itemData = start < data.length
          ? data.sublist(start, end)
          : Uint8List(0);
      packets.add(
        Utils.addPrefixToUint8List(
          <int>[command, messageId, packetCount, sequence],
          itemData,
        ),
      );
    }
    return packets;
  }
}
