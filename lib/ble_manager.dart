import 'dart:async';
import 'dart:typed_data';

import 'package:demo_ai_even/app.dart';
import 'package:demo_ai_even/runtime/privacy_safe_log.dart';
import 'package:demo_ai_even/services/ble.dart';
import 'package:demo_ai_even/services/evenai.dart';
import 'package:demo_ai_even/services/proto.dart';
import 'package:flutter/services.dart';

typedef SendResultParse = bool Function(Uint8List value);

class BleManager {
  BleManager._();

  Function()? onStatusChanged;

  static BleManager? _instance;
  static BleManager get() {
    final manager = _instance ??= BleManager._();
    return manager;
  }

  static const String methodSend = 'send';
  static const String _eventBleReceive = 'eventBleReceive';
  static const MethodChannel _channel = MethodChannel('method.bluetooth');

  final Stream<BleReceive> eventBleReceive = const EventChannel(
    _eventBleReceive,
  ).receiveBroadcastStream(_eventBleReceive).map(
        (dynamic value) => BleReceive.fromMap(value as Map),
      );

  StreamSubscription<BleReceive>? _receiveSubscription;
  Timer? beatHeartTimer;

  final List<Map<String, String>> pairedGlasses = <Map<String, String>>[];
  bool isConnected = false;
  String connectionStatus = 'Not connected';
  int tryTime = 0;

  void startListening() {
    if (_receiveSubscription != null) {
      return;
    }
    _receiveSubscription = eventBleReceive.listen(
      _handleReceivedData,
      onError: (Object error) {
        PrivacySafeLog.event(
          'ble_receive_error',
          fields: <String, Object?>{'error_type': error.runtimeType.toString()},
        );
      },
    );
  }

  Future<void> startScan() async {
    try {
      await _channel.invokeMethod<void>('startScan');
    } on PlatformException catch (error) {
      PrivacySafeLog.event(
        'ble_scan_start_failed',
        fields: <String, Object?>{'code': error.code},
      );
    }
  }

  Future<void> stopScan() async {
    try {
      await _channel.invokeMethod<void>('stopScan');
    } on PlatformException catch (error) {
      PrivacySafeLog.event(
        'ble_scan_stop_failed',
        fields: <String, Object?>{'code': error.code},
      );
    }
  }

  Future<void> connectToGlasses(String deviceName) async {
    try {
      await _channel.invokeMethod<void>(
        'connectToGlasses',
        <String, Object?>{'deviceName': deviceName},
      );
      connectionStatus = 'Connecting...';
      onStatusChanged?.call();
    } on PlatformException catch (error) {
      PrivacySafeLog.event(
        'ble_connect_failed',
        fields: <String, Object?>{'code': error.code},
      );
    }
  }

  void setMethodCallHandler() {
    _channel.setMethodCallHandler(_methodCallHandler);
  }

  Future<void> _methodCallHandler(MethodCall call) async {
    switch (call.method) {
      case 'glassesConnected':
        _onGlassesConnected(call.arguments);
        break;
      case 'glassesConnecting':
        _onGlassesConnecting();
        break;
      case 'glassesDisconnected':
        _onGlassesDisconnected();
        break;
      case 'foundPairedGlasses':
        final arguments = call.arguments;
        if (arguments is Map) {
          _onPairedGlassesFound(
            arguments.map(
              (dynamic key, dynamic value) =>
                  MapEntry(key.toString(), value.toString()),
            ),
          );
        }
        break;
      default:
        PrivacySafeLog.event(
          'ble_unknown_native_method',
          fields: <String, Object?>{'method': call.method},
        );
    }
  }

  void _onGlassesConnected(dynamic arguments) {
    final values = arguments is Map ? arguments : const <Object?, Object?>{};
    final leftName = values['leftDeviceName']?.toString() ?? 'left';
    final rightName = values['rightDeviceName']?.toString() ?? 'right';
    connectionStatus = 'Connected: \n$leftName \n$rightName';
    isConnected = true;
    onStatusChanged?.call();
    startSendBeatHeart();
    PrivacySafeLog.event('ble_connected');
  }

  void startSendBeatHeart() {
    beatHeartTimer?.cancel();
    beatHeartTimer = Timer.periodic(const Duration(seconds: 8), (_) async {
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
  }

  void _onGlassesConnecting() {
    connectionStatus = 'Connecting...';
    onStatusChanged?.call();
  }

  void _onGlassesDisconnected() {
    connectionStatus = 'Not connected';
    isConnected = false;
    beatHeartTimer?.cancel();
    beatHeartTimer = null;
    _failPendingRequests('device_disconnected');
    onStatusChanged?.call();
    PrivacySafeLog.event('ble_disconnected');
  }

  void _onPairedGlassesFound(Map<String, String> deviceInfo) {
    final channelNumber = deviceInfo['channelNumber'];
    if (channelNumber == null || channelNumber.isEmpty) {
      return;
    }
    final alreadyPaired = pairedGlasses.any(
      (Map<String, String> glasses) =>
          glasses['channelNumber'] == channelNumber,
    );
    if (!alreadyPaired) {
      pairedGlasses.add(Map.unmodifiable(deviceInfo));
    }
    onStatusChanged?.call();
  }

  void _handleReceivedData(BleReceive response) {
    if (response.type == 'VoiceChunk' || response.data.isEmpty) {
      return;
    }
    final command = response.getCmd();
    if (command == 0xF5 && response.data.length > 1) {
      final notifyIndex = response.data[1];
      switch (notifyIndex) {
        case 0:
          App.get.exitAll();
          break;
        case 1:
          if (response.lr == 'L') {
            EvenAI.get.lastPageByTouchpad();
          } else {
            EvenAI.get.nextPageByTouchpad();
          }
          break;
        case 23:
          unawaited(EvenAI.get.toStartEvenAIByOS());
          break;
        case 24:
          unawaited(EvenAI.get.recordOverByOS());
          break;
        default:
          PrivacySafeLog.event(
            'ble_unknown_device_event',
            fields: <String, Object?>{'event_index': notifyIndex},
          );
          break;
      }
      return;
    }

    final key = _requestKey(response.lr, command);
    final completer = _requestListeners.remove(key);
    _requestTimeouts.remove(key)?.cancel();
    if (completer != null && !completer.isCompleted) {
      completer.complete(response);
    }
    final next = _nextReceive;
    if (next != null && !next.isCompleted) {
      next.complete(response);
      _nextReceive = null;
    }
  }

  String getConnectionStatus() => connectionStatus;

  List<Map<String, String>> getPairedGlasses() =>
      List.unmodifiable(pairedGlasses);

  static final Map<String, Completer<BleReceive>> _requestListeners =
      <String, Completer<BleReceive>>{};
  static final Map<String, Timer> _requestTimeouts = <String, Timer>{};
  static Completer<BleReceive>? _nextReceive;

  static String _requestKey(String side, int command) =>
      '$side${command.toRadixString(16).padLeft(2, '0')}';

  static BleReceive _timeoutResponse() {
    final response = BleReceive()..isTimeout = true;
    return response;
  }

  static void _checkTimeout(String key, int timeoutMs) {
    _requestTimeouts.remove(key)?.cancel();
    final completer = _requestListeners.remove(key);
    if (completer != null && !completer.isCompleted) {
      completer.complete(_timeoutResponse());
      PrivacySafeLog.event(
        'ble_request_timeout',
        fields: <String, Object?>{'timeout_ms': timeoutMs},
      );
    }
  }

  void _failPendingRequests(String reason) {
    for (final completer in _requestListeners.values) {
      if (!completer.isCompleted) {
        completer.complete(_timeoutResponse());
      }
    }
    _requestListeners.clear();
    for (final timer in _requestTimeouts.values) {
      timer.cancel();
    }
    _requestTimeouts.clear();
    final next = _nextReceive;
    if (next != null && !next.isCompleted) {
      next.complete(_timeoutResponse());
    }
    _nextReceive = null;
    PrivacySafeLog.event(
      'ble_pending_requests_failed',
      fields: <String, Object?>{'reason': reason},
    );
  }

  static Future<T?> invokeMethod<T>(String method, [dynamic params]) =>
      _channel.invokeMethod<T>(method, params);

  static Future<BleReceive> requestRetry(
    Uint8List data, {
    String? lr,
    Map<String, dynamic>? other,
    int timeoutMs = 200,
    bool useNext = false,
    int retry = 3,
  }) async {
    for (var attempt = 0; attempt <= retry; attempt++) {
      final response = await request(
        data,
        lr: lr,
        other: other,
        timeoutMs: timeoutMs,
        useNext: useNext,
      );
      if (!response.isTimeout || !isBothConnected()) {
        return response;
      }
    }
    return _timeoutResponse();
  }

  static Future<bool> sendBoth(
    Uint8List data, {
    int timeoutMs = 250,
    SendResultParse? isSuccess,
    int retry = 0,
  }) async {
    final left = await requestRetry(
      data,
      lr: 'L',
      timeoutMs: timeoutMs,
      retry: retry,
    );
    if (left.isTimeout || left.data.length < 2) {
      return false;
    }
    final leftAccepted = isSuccess?.call(left.data) ?? left.data[1] == 0xc9;
    if (!leftAccepted) {
      return false;
    }
    final right = await requestRetry(
      data,
      lr: 'R',
      timeoutMs: timeoutMs,
      retry: retry,
    );
    if (right.isTimeout || right.data.length < 2) {
      return false;
    }
    return isSuccess?.call(right.data) ?? right.data[1] == 0xc9;
  }

  static Future<dynamic> sendData(
    Uint8List data, {
    String? lr,
    Map<String, dynamic>? other,
    int secondDelay = 100,
  }) async {
    final parameters = <String, dynamic>{'data': data, ...?other};
    if (lr != null) {
      parameters['lr'] = lr;
      return invokeMethod<dynamic>(methodSend, parameters);
    }

    parameters['lr'] = 'L';
    final left = await invokeMethod<dynamic>(methodSend, parameters);
    if (left != true && secondDelay > 0) {
      await Future<void>.delayed(Duration(milliseconds: secondDelay));
    }
    parameters['lr'] = 'R';
    return invokeMethod<dynamic>(methodSend, parameters);
  }

  static Future<BleReceive> request(
    Uint8List data, {
    String? lr,
    Map<String, dynamic>? other,
    int timeoutMs = 1000,
    bool useNext = false,
  }) async {
    if (data.isEmpty) {
      throw ArgumentError.value(data, 'data', 'must contain a command byte');
    }
    final side = lr ?? Proto.lR();
    final key = _requestKey(side, data[0]);
    final slotDeadline = DateTime.now().add(const Duration(seconds: 3));
    while (_requestListeners.containsKey(key)) {
      if (DateTime.now().isAfter(slotDeadline)) {
        return _timeoutResponse();
      }
      await Future<void>.delayed(const Duration(milliseconds: 5));
    }

    final completer = Completer<BleReceive>();
    if (useNext) {
      if (_nextReceive != null && !_nextReceive!.isCompleted) {
        return _timeoutResponse();
      }
      _nextReceive = completer;
    } else {
      _requestListeners[key] = completer;
    }
    if (timeoutMs > 0) {
      _requestTimeouts[key] = Timer(
        Duration(milliseconds: timeoutMs),
        () => _checkTimeout(key, timeoutMs),
      );
    }

    try {
      await sendData(data, lr: side, other: other).timeout(
        const Duration(seconds: 2),
      );
    } on Object {
      _requestTimeouts.remove(key)?.cancel();
      _requestListeners.remove(key);
      if (_nextReceive == completer) {
        _nextReceive = null;
      }
      if (!completer.isCompleted) {
        completer.complete(_timeoutResponse());
      }
    }

    final response = await completer.future;
    _requestTimeouts.remove(key)?.cancel();
    _requestListeners.remove(key);
    if (_nextReceive == completer) {
      _nextReceive = null;
    }
    return response;
  }

  static bool isBothConnected() => get().isConnected;

  static Future<bool> requestList(
    List<Uint8List> sendList, {
    String? lr,
    int? timeoutMs,
  }) async {
    if (sendList.isEmpty) {
      return false;
    }
    if (lr != null) {
      return _requestList(sendList, lr, timeoutMs: timeoutMs);
    }

    if (sendList.length == 1) {
      return sendBoth(sendList.single, timeoutMs: timeoutMs ?? 250);
    }
    final prefix = sendList.sublist(0, sendList.length - 1);
    final results = await Future.wait<bool>(<Future<bool>>[
      _requestList(prefix, 'L', timeoutMs: timeoutMs),
      _requestList(prefix, 'R', timeoutMs: timeoutMs),
    ]);
    if (!results.every((bool result) => result)) {
      return false;
    }
    return sendBoth(sendList.last, timeoutMs: timeoutMs ?? 250);
  }

  static Future<bool> _requestList(
    List<Uint8List> sendList,
    String lr, {
    int? timeoutMs,
  }) async {
    for (final packet in sendList) {
      final response = await request(
        packet,
        lr: lr,
        timeoutMs: timeoutMs ?? 350,
      );
      if (response.isTimeout || response.data.length < 2) {
        return false;
      }
      final status = response.data[1];
      if (status != 0xc9 && status != 0xcb) {
        return false;
      }
    }
    return true;
  }

  Future<void> dispose() async {
    beatHeartTimer?.cancel();
    await _receiveSubscription?.cancel();
    _receiveSubscription = null;
  }
}

extension Uint8ListEx on Uint8List {
  String get hexString =>
      map((int value) => value.toRadixString(16).padLeft(2, '0')).join(' ');
}
