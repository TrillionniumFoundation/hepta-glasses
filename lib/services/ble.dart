import 'dart:typed_data';

class BleReceive {
  String lr = '';
  Uint8List data = Uint8List(0);
  String type = '';
  bool isTimeout = false;

  int getCmd() {
    if (data.isEmpty) {
      throw StateError('BLE response has no command byte.');
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
        rawData.map((dynamic value) => value as int).toList(),
      );
    }
    response.type = map['type']?.toString() ?? '';
    return response;
  }

  String hexStringData() =>
      data.map((int value) => value.toRadixString(16).padLeft(2, '0')).join(' ');
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
