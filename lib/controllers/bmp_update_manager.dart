import 'dart:io';
import 'dart:math';
import 'dart:typed_data';

import 'package:crclib/catalog.dart';
import 'package:demo_ai_even/ble_manager.dart';
import 'package:demo_ai_even/runtime/privacy_safe_log.dart';
import 'package:demo_ai_even/utils/utils.dart';

/// Bounded, fail-closed G1 bitmap transfer.
final class BmpUpdateManager {
  static const int _packetPayloadBytes = 194;
  static const int _maximumPacketCount = 256;
  static const int _maximumImageBytes =
      _packetPayloadBytes * _maximumPacketCount;
  static const List<int> _storageAddress = <int>[0x00, 0x1c, 0x00, 0x00];
  static final Set<String> _activeSides = <String>{};

  Future<bool> updateBmp(String side, Uint8List image, {int? seq}) async {
    if (side != 'L' && side != 'R') {
      throw ArgumentError.value(side, 'side', 'must be L or R');
    }
    if (image.isEmpty || image.length > _maximumImageBytes) {
      PrivacySafeLog.event(
        'bitmap_transfer_rejected',
        fields: <String, Object?>{'bytes': image.length},
      );
      return false;
    }
    final packetCount =
        (image.length + _packetPayloadBytes - 1) ~/ _packetPayloadBytes;
    final resumeFrom = seq ?? 0;
    if (packetCount < 1 ||
        packetCount > _maximumPacketCount ||
        resumeFrom < 0 ||
        resumeFrom >= packetCount ||
        !_activeSides.add(side)) {
      return false;
    }

    try {
      for (var index = resumeFrom; index < packetCount; index++) {
        final start = index * _packetPayloadBytes;
        final end = min(start + _packetPayloadBytes, image.length);
        final payload = image.sublist(start, end);
        final prefix = index == 0
            ? <int>[0x15, index & 0xff, ..._storageAddress]
            : <int>[0x15, index & 0xff];
        final packet = Utils.addPrefixToUint8List(prefix, payload);
        final admitted = await BleManager.sendData(packet, lr: side);
        if (admitted != true) {
          PrivacySafeLog.event(
            'bitmap_packet_rejected',
            fields: <String, Object?>{
              'packet': index,
              'packet_count': packetCount,
            },
          );
          return false;
        }
        await Future<void>.delayed(
          Duration(milliseconds: Platform.isIOS ? 8 : 5),
        );
      }
      if (!await _finalize(side)) {
        return false;
      }
      return _verifyCrc(side, image);
    } on Object catch (error) {
      PrivacySafeLog.event(
        'bitmap_transfer_failed',
        fields: <String, Object?>{'error_type': error.runtimeType.toString()},
      );
      return false;
    } finally {
      _activeSides.remove(side);
    }
  }

  Future<bool> _finalize(String side) async {
    for (var attempt = 1; attempt <= 10; attempt++) {
      final response = await BleManager.request(
        Uint8List.fromList(const <int>[0x20, 0x0d, 0x0e]),
        lr: side,
        timeoutMs: 3000,
      );
      if (!response.isTimeout &&
          response.data.length >= 2 &&
          response.data[0] == 0x20 &&
          response.data[1] == 0xc9) {
        return true;
      }
      if (response.effectMayHaveOccurred) {
        PrivacySafeLog.event('bitmap_finalize_indeterminate');
        return false;
      }
      await Future<void>.delayed(const Duration(seconds: 1));
    }
    return false;
  }

  Future<bool> _verifyCrc(String side, Uint8List image) async {
    final addressed = Uint8List(_storageAddress.length + image.length)
      ..setRange(0, _storageAddress.length, _storageAddress)
      ..setRange(
        _storageAddress.length,
        _storageAddress.length + image.length,
        image,
      );
    final value = Crc32Xz().convert(addressed).toBigInt().toInt();
    final crc = Uint8List.fromList(<int>[
      (value >> 24) & 0xff,
      (value >> 16) & 0xff,
      (value >> 8) & 0xff,
      value & 0xff,
    ]);
    final response = await BleManager.request(
      Utils.addPrefixToUint8List(const <int>[0x16], crc),
      lr: side,
      timeoutMs: 3000,
    );
    return !response.isTimeout &&
        response.data.length >= 6 &&
        response.data[0] == 0x16 &&
        response.data[5] == 0xc9;
  }
}
