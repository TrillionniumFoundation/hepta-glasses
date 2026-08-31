import 'dart:io';
import 'dart:typed_data';

import 'package:crclib/catalog.dart';
import 'package:demo_ai_even/ble_manager.dart';
import 'package:demo_ai_even/runtime/privacy_safe_log.dart';
import 'package:demo_ai_even/services/ble.dart';
import 'package:demo_ai_even/utils/utils.dart';

typedef BmpPacketSender = Future<bool> Function(
  Uint8List packet,
  String side,
);
typedef BmpRequester = Future<BleReceive> Function(
  Uint8List packet,
  String side,
  int timeoutMs,
);
typedef BmpDelay = Future<void> Function(Duration duration);

final class BmpUpdateManager {
  BmpUpdateManager({
    BmpPacketSender? sendPacket,
    BmpRequester? request,
    BmpDelay? delay,
  })  : _sendPacket = sendPacket ?? _defaultSendPacket,
        _request = request ?? _defaultRequest,
        _delay = delay ?? _defaultDelay;

  static const int packetPayloadLength = 194;
  static const int maximumPacketCount = 256;
  static const int maximumImageBytes = packetPayloadLength * maximumPacketCount;
  static const List<int> _storageAddress = <int>[0x00, 0x1c, 0x00, 0x00];

  final BmpPacketSender _sendPacket;
  final BmpRequester _request;
  final BmpDelay _delay;

  Future<bool> updateBmp(String side, Uint8List image, {int? seq}) async {
    if (!_isValidSide(side) ||
        image.isEmpty ||
        image.length > maximumImageBytes) {
      return false;
    }

    final packets = _splitPackets(image);
    final startSequence = seq ?? 0;
    if (startSequence < 0 || startSequence >= packets.length) {
      return false;
    }

    for (var index = startSequence; index < packets.length; index++) {
      final packet = buildDataPacket(index, packets[index]);
      final accepted = await _sendPacket(packet, side);
      if (!accepted) {
        PrivacySafeLog.event(
          'bmp_packet_rejected',
          fields: <String, Object?>{
            'side': side,
            'sequence': index,
            'packet_count': packets.length,
          },
        );
        return false;
      }
      _reportProgress(side, index + 1, packets.length);
      if (index + 1 < packets.length) {
        await _delay(
          Duration(milliseconds: Platform.isIOS ? 8 : 5),
        );
      }
    }

    final finished = await _request(
      Uint8List.fromList(const <int>[0x20, 0x0d, 0x0e]),
      side,
      3000,
    );
    if (!isSuccessfulStatusResponse(finished, expectedCommand: 0x20)) {
      PrivacySafeLog.event(
        'bmp_finish_not_acknowledged',
        fields: <String, Object?>{
          'side': side,
          'indeterminate': finished.effectMayHaveOccurred,
          'error_code': finished.errorCode,
        },
      );
      return false;
    }

    final crcResponse = await _request(
      buildCrcCommand(image),
      side,
      1000,
    );
    final crcAccepted = isSuccessfulCrcResponse(crcResponse);
    if (!crcAccepted) {
      PrivacySafeLog.event(
        'bmp_crc_not_acknowledged',
        fields: <String, Object?>{
          'side': side,
          'indeterminate': crcResponse.effectMayHaveOccurred,
          'error_code': crcResponse.errorCode,
        },
      );
    }
    return crcAccepted;
  }

  static Uint8List buildDataPacket(int sequence, Uint8List payload) {
    if (sequence < 0 || sequence >= maximumPacketCount) {
      throw RangeError.range(
        sequence,
        0,
        maximumPacketCount - 1,
        'sequence',
      );
    }
    if (payload.isEmpty || payload.length > packetPayloadLength) {
      throw ArgumentError.value(
        payload.length,
        'payload',
        'must contain 1 to $packetPayloadLength bytes',
      );
    }
    final prefix = sequence == 0
        ? <int>[0x15, sequence, ..._storageAddress]
        : <int>[0x15, sequence];
    return Utils.addPrefixToUint8List(prefix, payload);
  }

  static Uint8List buildCrcCommand(Uint8List image) {
    if (image.isEmpty || image.length > maximumImageBytes) {
      throw ArgumentError.value(
        image.length,
        'image',
        'must contain 1 to $maximumImageBytes bytes',
      );
    }
    final crcInput = Uint8List(_storageAddress.length + image.length)
      ..setRange(0, _storageAddress.length, _storageAddress)
      ..setRange(
          _storageAddress.length, _storageAddress.length + image.length, image);
    final value = Crc32Xz().convert(crcInput).toBigInt().toInt();
    return Uint8List.fromList(<int>[
      0x16,
      value >> 24 & 0xff,
      value >> 16 & 0xff,
      value >> 8 & 0xff,
      value & 0xff,
    ]);
  }

  static bool isSuccessfulStatusResponse(
    BleReceive response, {
    required int expectedCommand,
  }) =>
      !response.isTimeout &&
      response.data.length >= 2 &&
      response.data[0] == expectedCommand &&
      response.data[1] == 0xc9;

  static bool isSuccessfulCrcResponse(BleReceive response) =>
      !response.isTimeout &&
      response.data.length >= 6 &&
      response.data[0] == 0x16 &&
      response.data[5] == 0xc9;

  static List<Uint8List> _splitPackets(Uint8List image) {
    final packets = <Uint8List>[];
    for (var offset = 0; offset < image.length; offset += packetPayloadLength) {
      final end = offset + packetPayloadLength < image.length
          ? offset + packetPayloadLength
          : image.length;
      packets.add(Uint8List.fromList(image.sublist(offset, end)));
    }
    return packets;
  }

  static bool _isValidSide(String side) => side == 'L' || side == 'R';

  void _reportProgress(String side, int sent, int total) {
    PrivacySafeLog.event(
      'bmp_transfer_progress',
      fields: <String, Object?>{
        'side': side,
        'sent_packets': sent,
        'packet_count': total,
      },
    );
  }

  static Future<bool> _defaultSendPacket(
    Uint8List packet,
    String side,
  ) =>
      BleManager.sendData(packet, lr: side);

  static Future<BleReceive> _defaultRequest(
    Uint8List packet,
    String side,
    int timeoutMs,
  ) =>
      BleManager.request(packet, lr: side, timeoutMs: timeoutMs);

  static Future<void> _defaultDelay(Duration duration) =>
      Future<void>.delayed(duration);
}
