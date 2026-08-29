import 'dart:typed_data';

final class PacketCodec {
  const PacketCodec();

  List<Uint8List> fragment({
    required int command,
    required Uint8List payload,
    int maxPacketBytes = 20,
    List<int> metadata = const <int>[],
  }) {
    _validateByte(command, 'command');
    for (var index = 0; index < metadata.length; index++) {
      _validateByte(metadata[index], 'metadata[$index]');
    }
    final headerBytes = 3 + metadata.length;
    if (maxPacketBytes <= headerBytes) {
      throw ArgumentError.value(
        maxPacketBytes,
        'maxPacketBytes',
        'must leave room for payload bytes',
      );
    }
    final chunkBytes = maxPacketBytes - headerBytes;
    final frameCount = payload.isEmpty
        ? 1
        : (payload.length + chunkBytes - 1) ~/ chunkBytes;
    if (frameCount > 255) {
      throw StateError('Payload requires more than 255 protocol frames.');
    }

    final frames = <Uint8List>[];
    for (var sequence = 0; sequence < frameCount; sequence++) {
      final start = sequence * chunkBytes;
      final end = payload.isEmpty
          ? 0
          : (start + chunkBytes < payload.length
              ? start + chunkBytes
              : payload.length);
      frames.add(
        Uint8List.fromList(<int>[
          command,
          frameCount,
          sequence,
          ...metadata,
          ...payload.sublist(start, end),
        ]),
      );
    }
    return List.unmodifiable(frames);
  }

  Uint8List reassemble(
    List<Uint8List> frames, {
    int? expectedCommand,
    int metadataLength = 0,
  }) {
    if (frames.isEmpty) {
      throw const FormatException('At least one frame is required.');
    }
    if (metadataLength < 0) {
      throw ArgumentError.value(metadataLength, 'metadataLength');
    }
    final headerBytes = 3 + metadataLength;
    final first = frames.first;
    if (first.length < headerBytes) {
      throw const FormatException('Frame is shorter than its header.');
    }
    final command = first[0];
    final total = first[1];
    if (total == 0 || total != frames.length) {
      throw const FormatException('Frame count does not match header.');
    }
    if (expectedCommand != null && command != expectedCommand) {
      throw const FormatException('Unexpected command.');
    }

    final ordered = List<Uint8List?>.filled(total, null);
    for (final frame in frames) {
      if (frame.length < headerBytes || frame[0] != command || frame[1] != total) {
        throw const FormatException('Inconsistent frame header.');
      }
      final sequence = frame[2];
      if (sequence >= total || ordered[sequence] != null) {
        throw const FormatException('Duplicate or invalid frame sequence.');
      }
      ordered[sequence] = frame;
    }
    if (ordered.any((frame) => frame == null)) {
      throw const FormatException('Missing frame sequence.');
    }

    final builder = BytesBuilder(copy: false);
    for (final frame in ordered) {
      builder.add(frame!.sublist(headerBytes));
    }
    return builder.takeBytes();
  }

  static void _validateByte(int value, String name) {
    if (value < 0 || value > 255) {
      throw RangeError.range(value, 0, 255, name);
    }
  }
}
