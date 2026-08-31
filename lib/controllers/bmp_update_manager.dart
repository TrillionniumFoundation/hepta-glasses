import 'dart:async';
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
      throw ArgumentError.value(image.length, 'image',
          'BMP payload must be between 1 and $maximumImageBytes bytes');
    }
    final packets = <Uint8List>[];
    for (var offset = 0; offset < image.length; offset += packetPayloadBytes) {
      final end = min(offset + packetPayloadBytes, image.length);
      final sequence = packets.length;
      if (sequence >= maximumPacketCount) {
        throw StateError(
            'BMP packet sequence exceeds one-byte protocol range.');
      }
      final payload = image.sublist(offset, end);
      final prefix = sequence == 0
          ? <int>[0x15, sequence, ...storageAddress]
          : <int>[0x15, sequence];
      packets.add(Utils.addPrefixToUint8List(prefix, payload));
    }
    return List<Uint8List>.unmodifiable(packets);
  }

  static Uint8List crcPayload(Uint8List image) =>
      Utils.addPrefixToUint8List(storageAddress, image);

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
      PrivacySafeLog.event('bmp_transfer_rejected',
          fields: <String, Object?>{'side': lr, 'reason': 'already_running'});
      return false;
    }
    final List<Uint8List> packets;
    try {
      packets = BmpTransferCodec.buildPackets(image);
    } on Object catch (error) {
      PrivacySafeLog.event('bmp_transfer_rejected', fields: <String, Object?>{
        'side': lr,
        'reason': 'invalid_payload',
        'error_type': error.runtimeType.toString()
      });
      return false;
    }
    final startSequence = seq ?? 0;
    if (startSequence < 0 || startSequence >= packets.length) {
      return false;
    }
    _activeSides.add(lr);
    isTransfering = true;
    try {
      PrivacySafeLog.event('bmp_transfer_started', fields: <String, Object?>{
        'side': lr,
        'bytes': image.length,
        'packets': packets.length,
        'start_sequence': startSequence
      });
      for (var index = startSequence; index < packets.length; index++) {
        final queued = await BleManager.sendData(packets[index], lr: lr);
        if (queued == false) {
          PrivacySafeLog.event('bmp_packet_rejected',
              fields: <String, Object?>{'side': lr, 'sequence': index});
          return false;
        }
        await Future<void>.delayed(
            Duration(milliseconds: Platform.isIOS ? 8 : 5));
      }
      final finish = await BleManager.request(
          Uint8List.fromList(<int>[0x20, 0x0d, 0x0e]),
          lr: lr,
          timeoutMs: 3000);
      if (finish.isTimeout ||
          !BmpTransferCodec.isSuccessResponse(finish.data)) {
        PrivacySafeLog.event('bmp_finish_unacknowledged',
            fields: <String, Object?>{
              'side': lr,
              'effect_may_have_occurred': finish.effectMayHaveOccurred
            });
        return false;
      }
      final checksum = Crc32Xz()
          .convert(BmpTransferCodec.crcPayload(image))
          .toBigInt()
          .toInt();
      final crc = Uint8List.fromList(<int>[
        checksum >> 24 & 0xff,
        checksum >> 16 & 0xff,
        checksum >> 8 & 0xff,
        checksum & 0xff
      ]);
      final checked = await BleManager.request(
          Utils.addPrefixToUint8List(<int>[0x16], crc),
          lr: lr,
          timeoutMs: 3000);
      final success = !checked.isTimeout &&
          BmpTransferCodec.isSuccessResponse(checked.data);
      PrivacySafeLog.event(
          success ? 'bmp_transfer_completed' : 'bmp_crc_unacknowledged',
          fields: <String, Object?>{
            'side': lr,
            'bytes': image.length,
            'packets': packets.length,
            if (!success)
              'effect_may_have_occurred': checked.effectMayHaveOccurred
          });
      return success;
    } on TimeoutException {
      PrivacySafeLog.event('bmp_transfer_timeout',
          fields: <String, Object?>{'side': lr});
      return false;
    } on Object catch (error) {
      PrivacySafeLog.event('bmp_transfer_failed', fields: <String, Object?>{
        'side': lr,
        'error_type': error.runtimeType.toString()
      });
      return false;
    } finally {
      _activeSides.remove(lr);
      isTransfering = _activeSides.isNotEmpty;
    }
  }
}
