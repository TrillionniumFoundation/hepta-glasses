import 'dart:typed_data';

class BleReceive {
  String lr = '';
  Uint8List data = Uint8List(0);
  String type = '';
  bool isTimeout = false;
  bool effectMayHaveOccurred = false;
  int generation = 0;
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
