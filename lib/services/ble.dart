import 'dart:async';
import 'dart:typed_data';

const String unselectedBlePairIdentity = 'unselected';

/// Read-only connection authority consumed by transports and coordinators.
///
/// A snapshot is an immutable capability boundary: callers must bind a write
/// to its pair identity and connection generation rather than consulting
/// mutable global state after an asynchronous boundary.
abstract interface class BleConnectionSource {
  Stream<BleConnectionSnapshot> get connectionSnapshots;

  BleConnectionSnapshot get connectionSnapshot;
}

final class BleConnectionSnapshot {
  const BleConnectionSnapshot({
    required this.leftConnected,
    required this.rightConnected,
    required this.generation,
    this.pairIdentity = unselectedBlePairIdentity,
  })  : assert(generation >= 0),
        assert(pairIdentity != '');

  final bool leftConnected;
  final bool rightConnected;
  final int generation;
  final String pairIdentity;

  bool get bothConnected => leftConnected && rightConnected;

  bool isSideConnected(String side) =>
      side == 'L'
          ? leftConnected
          : side == 'R'
              ? rightConnected
              : false;

  bool get hasAuthoritativeIdentity =>
      generation > 0 && pairIdentity != unselectedBlePairIdentity;
}

class BleReceive {
  String lr = '';
  Uint8List data = Uint8List(0);
  String type = '';
  bool isTimeout = false;
  bool effectMayHaveOccurred = false;
  int generation = 0;
  String pairIdentity = unselectedBlePairIdentity;
  String? errorCode;

  int getCmd() {
    if (data.isEmpty) {
      throw StateError('BLE response does not contain a command byte.');
    }
    return data[0];
  }

  BleReceive();

  static BleReceive fromMap(Map<dynamic, dynamic> map) {
    final response = BleReceive();
    response.lr = map['lr']?.toString() ?? '';
    final rawData = map['data'];
    if (rawData is Uint8List) {
      response.data = rawData;
    } else if (rawData is List) {
      response.data = Uint8List.fromList(
        rawData.map((dynamic value) => value as int).toList(growable: false),
      );
    }
    response.type = map['type']?.toString() ?? '';
    final rawGeneration = map['generation'];
    if (rawGeneration is int) {
      response.generation = rawGeneration;
    }
    final rawPairIdentity = map['pairIdentity'];
    if (rawPairIdentity is String && rawPairIdentity.isNotEmpty) {
      response.pairIdentity = rawPairIdentity;
    }
    return response;
  }

  String hexStringData() => data
      .map((int value) => value.toRadixString(16).padLeft(2, '0'))
      .join(' ');
}

enum BleEvent {
  exitFunc,
  nextPageForEvenAI,
  upHeader,
  downHeader,
  glassesConnectSuccess,
  evenaiStart,
  evenaiRecordOver,
}
