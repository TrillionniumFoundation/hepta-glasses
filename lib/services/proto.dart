import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';

import 'package:demo_ai_even/ble_manager.dart';
import 'package:demo_ai_even/runtime/contracts.dart';
import 'package:demo_ai_even/runtime/device_effect_result.dart';
import 'package:demo_ai_even/runtime/hepta_runtime.dart';
import 'package:demo_ai_even/runtime/privacy_safe_log.dart';
import 'package:demo_ai_even/services/ble.dart';
import 'package:demo_ai_even/services/evenai_proto.dart';
import 'package:demo_ai_even/utils/utils.dart';

class Proto {
  Proto._();

  static String lR() => BleManager.isBothConnected() ? 'R' : 'L';

  /// Public microphone admission path. Once the deterministic runtime is
  /// initialized, microphone activation cannot bypass PolicyEngine and
  /// ToolGateway. The injected low-level effect uses [micOnDirectEffect] to
  /// avoid a recursive gateway call.
  static Future<(int, bool)> micOn({String? lr, int attempt = 1}) async {
    final result = await micOnResult(lr: lr, attempt: attempt);
    return (result.$1, result.$2.committed);
  }

  static Future<(int, DeviceEffectResult)> micOnResult({
    String? lr,
    int attempt = 1,
  }) async {
    final startedAt = Utils.getTimestampMs();
    if (!HeptaRuntime.isInitialized) {
      final direct = await micOnDirectEffect(lr: lr);
      return (direct.$1, direct.$2);
    }
    final session = HeptaRuntime.current.sessions.current;
    if (session == null || session.terminal) {
      PrivacySafeLog.event('microphone_command_rejected_without_session');
      return (
        startedAt,
        DeviceEffectResult.rejectedBeforeWrite(
          code: 'assistant_session_unavailable',
        ),
      );
    }
    final receipt = await HeptaRuntime.current.openMicrophone(
      session: session.token,
      side: lr ?? 'R',
      attempt: attempt,
    );
    return (startedAt, _effectFromReceipt(receipt));
  }

  /// Native protocol effect used only by the runtime capability adapter.
  static Future<(int, bool)> micOnDirect({String? lr}) async {
    final result = await micOnDirectEffect(lr: lr);
    return (result.$1, result.$2.committed);
  }

  static Future<(int, DeviceEffectResult)> micOnDirectEffect({
    String? lr,
  }) async {
    final begin = Utils.getTimestampMs();
    final side = lr ?? lR();
    final data = Uint8List.fromList(<int>[0x0E, 0x01]);
    final receive = await BleManager.request(data, lr: side);
    final end = Utils.getTimestampMs();
    final startMic = begin + ((end - begin) ~/ 2);
    final outcome = _responseOutcome(
      receive,
      externalId: 'microphone:$side:${receive.generation}:0x0e',
      accepts: (BleReceive response) => _isAck(response.data),
    );
    PrivacySafeLog.event(
      'microphone_command_completed',
      fields: <String, Object?>{
        'disposition': outcome.disposition.name,
        'code': outcome.code,
      },
    );
    return (startMic, outcome);
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
  }) async =>
      (await sendEvenAIDataEffect(
        text,
        timeoutMs: timeoutMs,
        newScreen: newScreen,
        pos: pos,
        currentPageNumber: currentPageNumber,
        maxPageNumber: maxPageNumber,
        current_page_num: current_page_num,
        max_page_num: max_page_num,
      ))
          .committed;

  static Future<DeviceEffectResult> sendEvenAIDataEffect(
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
      currentPageNumber: currentPage,
      maxPageNumber: maximumPage,
    );
    _evenAiSequence = (_evenAiSequence + 1) & 0xff;
    if (packets.isEmpty) {
      return DeviceEffectResult.rejectedBeforeWrite(
        code: 'display_packet_list_empty',
      );
    }

    return _sendSequenceToBothLegs(
      packets,
      operation: 'display:$syncSequence',
      timeoutMs: timeoutMs ?? 2000,
    );
  }

  static int _heartbeatSequence = 0;

  static Future<bool> sendHeartBeat() async =>
      (await sendHeartBeatEffect()).committed;

  static Future<DeviceEffectResult> sendHeartBeatEffect() async {
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

    return _sendSequenceToBothLegs(
      <Uint8List>[data],
      operation: 'heartbeat:$sequence',
      timeoutMs: 1500,
      accepts: _isHeartbeatAck,
    );
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

  static Future<bool> exit() async => (await exitEffect()).committed;

  static Future<DeviceEffectResult> exitEffect() async =>
      _sendSequenceToBothLegs(
        <Uint8List>[
          Uint8List.fromList(<int>[0x18])
        ],
        operation: 'exit-mode',
        timeoutMs: 1500,
      );

  static List<Uint8List> _getPackList(
    int command,
    Uint8List data, {
    int count = 20,
  }) {
    if (count <= 3) {
      throw ArgumentError.value(count, 'count', 'must exceed header size');
    }
    final payloadBytes = count - 3;
    final packetCount = max(
      1,
      (data.length + payloadBytes - 1) ~/ payloadBytes,
    );
    if (packetCount > 255) {
      throw StateError('Payload exceeds protocol packet limit.');
    }
    final packets = <Uint8List>[];
    for (var sequence = 0; sequence < packetCount; sequence++) {
      final start = sequence * payloadBytes;
      final end = start + payloadBytes < data.length
          ? start + payloadBytes
          : data.length;
      final itemData =
          start < data.length ? data.sublist(start, end) : Uint8List(0);
      packets.add(
        Utils.addPrefixToUint8List(<int>[
          command,
          packetCount,
          sequence,
        ], itemData),
      );
    }
    return packets;
  }

  static Future<bool> sendNewAppWhiteListJson(String whitelistJson) async =>
      (await sendNewAppWhiteListEffect(whitelistJson)).committed;

  static Future<DeviceEffectResult> sendNewAppWhiteListEffect(
    String whitelistJson,
  ) async {
    final packets = _getPackList(
      0x04,
      Uint8List.fromList(utf8.encode(whitelistJson)),
      count: 180,
    );
    final outcome = await _sendSequenceToSide(
      packets,
      side: 'L',
      operation: 'notification-whitelist',
      timeoutMs: 300,
    );
    if (!outcome.committed) {
      PrivacySafeLog.event(
        'whitelist_send_failed',
        fields: <String, Object?>{
          'packets': packets.length,
          'disposition': outcome.disposition.name,
          'code': outcome.code,
        },
      );
    }
    return outcome;
  }

  static Future<bool> sendNotify(
    Map<Object?, Object?> appData,
    int notifyId, {
    int retry = 0,
  }) async =>
      (await sendNotifyEffect(appData, notifyId)).committed;

  static Future<DeviceEffectResult> sendNotifyEffect(
    Map<Object?, Object?> appData,
    int notifyId,
  ) async {
    final notifyJson = jsonEncode(<String, Object?>{
      'ncs_notification': appData,
    });
    final packets = _getNotifyPackList(
      0x4B,
      notifyId,
      Uint8List.fromList(utf8.encode(notifyJson)),
    );
    final outcome = await _sendSequenceToSide(
      packets,
      side: 'L',
      operation: 'notification:$notifyId',
      timeoutMs: 1000,
    );
    if (!outcome.committed) {
      PrivacySafeLog.event(
        'notification_send_failed',
        fields: <String, Object?>{
          'notification_id': notifyId,
          'packets': packets.length,
          'disposition': outcome.disposition.name,
          'code': outcome.code,
        },
      );
    }
    return outcome;
  }

  static List<Uint8List> _getNotifyPackList(
    int command,
    int messageId,
    Uint8List data,
  ) {
    const payloadBytes = 176;
    final packetCount = max(
      1,
      (data.length + payloadBytes - 1) ~/ payloadBytes,
    );
    if (packetCount > 255) {
      throw StateError('Notification exceeds protocol packet limit.');
    }
    final packets = <Uint8List>[];
    for (var sequence = 0; sequence < packetCount; sequence++) {
      final start = sequence * payloadBytes;
      final end = start + payloadBytes < data.length
          ? start + payloadBytes
          : data.length;
      final itemData =
          start < data.length ? data.sublist(start, end) : Uint8List(0);
      packets.add(
        Utils.addPrefixToUint8List(<int>[
          command,
          messageId,
          packetCount,
          sequence,
        ], itemData),
      );
    }
    return packets;
  }

  static Future<DeviceEffectResult> _sendSequenceToBothLegs(
    List<Uint8List> packets, {
    required String operation,
    required int timeoutMs,
    bool Function(BleReceive response)? accepts,
  }) async {
    final left = await _sendSequenceToSide(
      packets,
      side: 'L',
      operation: operation,
      timeoutMs: timeoutMs,
      accepts: accepts,
    );
    if (!left.committed) {
      return left;
    }
    final right = await _sendSequenceToSide(
      packets,
      side: 'R',
      operation: operation,
      timeoutMs: timeoutMs,
      accepts: accepts,
    );
    return DeviceEffectResult.aggregate(
      <DeviceEffectResult>[left, right],
      externalId: '$operation:pair',
      partialCode: 'dual_leg_partial_effect_indeterminate',
    );
  }

  static Future<DeviceEffectResult> _sendSequenceToSide(
    List<Uint8List> packets, {
    required String side,
    required String operation,
    required int timeoutMs,
    bool Function(BleReceive response)? accepts,
  }) async {
    if (packets.isEmpty) {
      return DeviceEffectResult.rejectedBeforeWrite(
        code: 'packet_list_empty',
        externalId: '$operation:$side',
      );
    }
    final outcomes = <DeviceEffectResult>[];
    for (var index = 0; index < packets.length; index++) {
      final response = await BleManager.request(
        packets[index],
        lr: side,
        timeoutMs: timeoutMs,
      );
      final outcome = _responseOutcome(
        response,
        externalId: '$operation:$side:$index',
        accepts: accepts ??
            (BleReceive value) => !value.isTimeout && _isAck(value.data),
      );
      outcomes.add(outcome);
      if (!outcome.committed) {
        return DeviceEffectResult.aggregate(
          outcomes,
          externalId: '$operation:$side',
          partialCode: 'packet_sequence_partial_effect_indeterminate',
        );
      }
    }
    return DeviceEffectResult.committed(
      externalId: '$operation:$side',
      details: <String, Object?>{'packet_count': packets.length},
    );
  }

  static DeviceEffectResult _responseOutcome(
    BleReceive response, {
    required String externalId,
    required bool Function(BleReceive response) accepts,
  }) {
    if (accepts(response)) {
      return DeviceEffectResult.committed(
        externalId: externalId,
        details: <String, Object?>{
          'generation': response.generation,
          'side': response.lr,
        },
      );
    }
    if (response.effectMayHaveOccurred) {
      return DeviceEffectResult.indeterminate(
        code: response.errorCode ?? 'ack_missing_after_native_write',
        externalId: externalId,
        details: <String, Object?>{
          'generation': response.generation,
          'side': response.lr,
        },
      );
    }
    if (response.isTimeout) {
      return DeviceEffectResult.rejectedBeforeWrite(
        code: response.errorCode ?? 'request_rejected_before_write',
        externalId: externalId,
        details: <String, Object?>{
          'generation': response.generation,
          'side': response.lr,
        },
      );
    }
    // A response arrived after bytes were written but did not satisfy the
    // command contract. Conservatively require reconciliation.
    return DeviceEffectResult.indeterminate(
      code: response.errorCode ?? 'negative_or_malformed_ack_after_write',
      externalId: externalId,
      details: <String, Object?>{
        'generation': response.generation,
        'side': response.lr,
        'response_length': response.data.length,
      },
    );
  }

  static DeviceEffectResult _effectFromReceipt(ToolReceipt receipt) {
    final code =
        receipt.result['error_code']?.toString() ?? receipt.policyReason;
    final externalId = receipt.result['external_id']?.toString();
    if (receipt.status == ToolReceiptStatus.succeeded) {
      return DeviceEffectResult.committed(
        code: code,
        externalId: externalId,
        details: receipt.result,
      );
    }
    if (receipt.result['retry_safe'] == true &&
        receipt.result['effect_may_have_occurred'] != true) {
      return DeviceEffectResult.rejectedBeforeWrite(
        code: code,
        externalId: externalId,
        details: receipt.result,
      );
    }
    return DeviceEffectResult.indeterminate(
      code: code,
      externalId: externalId ?? receipt.idempotencyKey,
      details: receipt.result,
    );
  }
}
