import 'dart:async';
import 'dart:typed_data';

import 'package:demo_ai_even/app.dart';
import 'package:demo_ai_even/runtime/privacy_safe_log.dart';
import 'package:demo_ai_even/services/ble.dart';
import 'package:demo_ai_even/services/evenai.dart';
import 'package:demo_ai_even/services/proto.dart';
import 'package:flutter/services.dart';

typedef SendResultParse = bool Function(Uint8List value);

final class _PendingBleRequest {
  const _PendingBleRequest({
    required this.completer,
    required this.generation,
  });

  final Completer<BleReceive> completer;
  final int generation;
}

class BleManager {
  BleManager._();

  Function()? onStatusChanged;

  static BleManager? _instance;
  static BleManager get() => _instance ??= BleManager._();

  static const String methodSend = 'send';
  static const String _eventBleReceive = 'eventBleReceive';
  static const MethodChannel _channel = MethodChannel('method.bluetooth');

  final Stream<BleReceive> eventBleReceive = const EventChannel(
    _eventBleReceive,
  ).receiveBroadcastStream(_eventBleReceive).map(
        (dynamic value) => BleReceive.fromMap(value as Map<dynamic, dynamic>),
      );

  StreamSubscription<BleReceive>? _receiveSubscription;
  Timer? beatHeartTimer;

  final List<Map<String, String>> pairedGlasses = <Map<String, String>>[];
  bool isConnected = false;
  String connectionStatus = 'Not connected';
  int tryTime = 0;
  int _connectionGeneration = 0;

  int get connectionGeneration => _connectionGeneration;

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

  Future<void> disconnectFromGlasses() async {
    try {
      await _channel.invokeMethod<void>('disconnectFromGlasses');
    } on PlatformException catch (error) {
      PrivacySafeLog.event(
        'ble_disconnect_failed',
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
        _onGlassesConnecting(call.arguments);
        break;
      case 'glassesDisconnected':
        _onGlassesDisconnected(call.arguments);
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

  int _generationFrom(dynamic arguments) {
    if (arguments is Map && arguments['generation'] is int) {
      return arguments['generation']! as int;
    }
    return 0;
  }

  void _adoptGeneration(int generation) {
    if (generation <= 0 || generation == _connectionGeneration) {
      return;
    }
    _connectionGeneration = generation;
    _failPendingRequests(
      'connection_generation_changed',
      effectMayHaveOccurred: true,
    );
    _quarantinedRequestKeys.clear();
  }

  bool _isStaleGeneration(int generation) =>
      generation > 0 &&
      _connectionGeneration > 0 &&
      generation < _connectionGeneration;

  void _onGlassesConnected(dynamic arguments) {
    final generation = _generationFrom(arguments);
    if (_isStaleGeneration(generation)) {
      return;
    }
    _adoptGeneration(generation);
    final values = arguments is Map ? arguments : const <Object?, Object?>{};
    final leftName = values['leftDeviceName']?.toString() ?? 'left';
    final rightName = values['rightDeviceName']?.toString() ?? 'right';
    connectionStatus = 'Connected: \n$leftName \n$rightName';
    isConnected = true;
    onStatusChanged?.call();
    startSendBeatHeart();
    PrivacySafeLog.event(
      'ble_connected',
      fields: <String, Object?>{'generation': _connectionGeneration},
    );
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

  void _onGlassesConnecting(dynamic arguments) {
    final generation = _generationFrom(arguments);
    if (_isStaleGeneration(generation)) {
      return;
    }
    _adoptGeneration(generation);
    connectionStatus = 'Connecting...';
    isConnected = false;
    onStatusChanged?.call();
  }

  void _onGlassesDisconnected(dynamic arguments) {
    final generation = _generationFrom(arguments);
    if (_isStaleGeneration(generation)) {
      return;
    }
    _adoptGeneration(generation);
    connectionStatus = 'Not connected';
    isConnected = false;
    beatHeartTimer?.cancel();
    beatHeartTimer = null;
    _failPendingRequests(
      'device_disconnected',
      effectMayHaveOccurred: true,
    );
    _quarantinedRequestKeys.clear();
    onStatusChanged?.call();
    PrivacySafeLog.event(
      'ble_disconnected',
      fields: <String, Object?>{'generation': _connectionGeneration},
    );
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
    if (response.generation > 0 &&
        _connectionGeneration > 0 &&
        response.generation != _connectionGeneration) {
      PrivacySafeLog.event(
        'ble_stale_generation_response',
        fields: <String, Object?>{
          'response_generation': response.generation,
          'current_generation': _connectionGeneration,
        },
      );
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
      }
      return;
    }

    final key = _requestKey(response.lr, command);
    final pending = _requestListeners.remove(key);
    _requestTimeouts.remove(key)?.cancel();
    if (pending != null && !pending.completer.isCompleted) {
      if (pending.generation == _connectionGeneration ||
          _connectionGeneration == 0) {
        pending.completer.complete(response);
      } else {
        pending.completer.complete(
          _timeoutResponse(
            effectMayHaveOccurred: true,
            generation: pending.generation,
            errorCode: 'connection_generation_changed',
          ),
        );
      }
      return;
    }

    if (_quarantinedRequestKeys.remove(key)) {
      PrivacySafeLog.event(
        'ble_late_response_observed',
        fields: <String, Object?>{
          'generation': _connectionGeneration,
          'command': command,
        },
      );
      return;
    }

    final next = _nextReceive;
    if (next != null && !next.completer.isCompleted) {
      if (next.generation == _connectionGeneration ||
          _connectionGeneration == 0) {
        next.completer.complete(response);
      } else {
        next.completer.complete(
          _timeoutResponse(
            effectMayHaveOccurred: true,
            generation: next.generation,
            errorCode: 'connection_generation_changed',
          ),
        );
      }
      _nextReceive = null;
      _nextReceiveKey = null;
    }
  }

  String getConnectionStatus() => connectionStatus;

  List<Map<String, String>> getPairedGlasses() =>
      List.unmodifiable(pairedGlasses);

  static final Map<String, _PendingBleRequest> _requestListeners =
      <String, _PendingBleRequest>{};
  static final Map<String, Timer> _requestTimeouts = <String, Timer>{};
  static final Set<String> _quarantinedRequestKeys = <String>{};
  static _PendingBleRequest? _nextReceive;
  static String? _nextReceiveKey;

  static String _requestKey(String side, int command) =>
      '$side${command.toRadixString(16).padLeft(2, '0')}';

  static BleReceive _timeoutResponse({
    bool effectMayHaveOccurred = false,
    int? generation,
    String? errorCode,
  }) {
    final response = BleReceive()
      ..isTimeout = true
      ..effectMayHaveOccurred = effectMayHaveOccurred
      ..generation = generation ?? get()._connectionGeneration
      ..errorCode = errorCode;
    return response;
  }

  static void _checkTimeout(
    String key,
    int timeoutMs,
    int generation,
  ) {
    _requestTimeouts.remove(key)?.cancel();
    final pending = _requestListeners.remove(key);
    if (pending != null && !pending.completer.isCompleted) {
      _quarantinedRequestKeys.add(key);
      pending.completer.complete(
        _timeoutResponse(
          effectMayHaveOccurred: true,
          generation: generation,
          errorCode: 'ack_timeout_after_native_write',
        ),
      );
      PrivacySafeLog.event(
        'ble_request_timeout',
        fields: <String, Object?>{
          'timeout_ms': timeoutMs,
          'generation': generation,
        },
      );
    }
    final next = _nextReceive;
    if (_nextReceiveKey == key &&
        next != null &&
        !next.completer.isCompleted) {
      _quarantinedRequestKeys.add(key);
      next.completer.complete(
        _timeoutResponse(
          effectMayHaveOccurred: true,
          generation: generation,
          errorCode: 'ack_timeout_after_native_write',
        ),
      );
      _nextReceive = null;
      _nextReceiveKey = null;
    }
  }

  void _failPendingRequests(
    String reason, {
    required bool effectMayHaveOccurred,
  }) {
    for (final MapEntry<String, _PendingBleRequest> entry
        in _requestListeners.entries) {
      final pending = entry.value;
      if (!pending.completer.isCompleted) {
        pending.completer.complete(
          _timeoutResponse(
            effectMayHaveOccurred: effectMayHaveOccurred,
            generation: pending.generation,
            errorCode: reason,
          ),
        );
      }
    }
    _requestListeners.clear();
    for (final timer in _requestTimeouts.values) {
      timer.cancel();
    }
    _requestTimeouts.clear();
    final next = _nextReceive;
    if (next != null && !next.completer.isCompleted) {
      next.completer.complete(
        _timeoutResponse(
          effectMayHaveOccurred: effectMayHaveOccurred,
          generation: next.generation,
          errorCode: reason,
        ),
      );
    }
    _nextReceive = null;
    _nextReceiveKey = null;
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
      if (!response.isTimeout ||
          response.effectMayHaveOccurred ||
          !isBothConnected()) {
        return response;
      }
    }
    return _timeoutResponse(
      effectMayHaveOccurred: false,
      errorCode: 'retry_budget_exhausted_before_write',
    );
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

  static Future<bool> sendData(
    Uint8List data, {
    String? lr,
    Map<String, dynamic>? other,
    int secondDelay = 100,
  }) async {
    final parameters = <String, dynamic>{'data': data, ...?other};
    if (lr != null) {
      parameters['lr'] = lr;
      return await invokeMethod<bool>(methodSend, parameters) == true;
    }

    parameters['lr'] = 'L';
    final left = await invokeMethod<bool>(methodSend, parameters) == true;
    if (!left) {
      return false;
    }
    if (secondDelay > 0) {
      await Future<void>.delayed(Duration(milliseconds: secondDelay));
    }
    parameters['lr'] = 'R';
    return await invokeMethod<bool>(methodSend, parameters) == true;
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
    final manager = get();
    final generation = manager._connectionGeneration;
    final side = lr ?? Proto.lR();
    final key = _requestKey(side, data[0]);
    if (_quarantinedRequestKeys.contains(key)) {
      return _timeoutResponse(
        effectMayHaveOccurred: true,
        generation: generation,
        errorCode: 'request_slot_quarantined',
      );
    }

    final slotDeadline = DateTime.now().add(const Duration(seconds: 3));
    while (_requestListeners.containsKey(key)) {
      if (manager._connectionGeneration != generation) {
        return _timeoutResponse(
          effectMayHaveOccurred: false,
          generation: generation,
          errorCode: 'connection_generation_changed_before_write',
        );
      }
      if (DateTime.now().isAfter(slotDeadline)) {
        return _timeoutResponse(
          effectMayHaveOccurred: false,
          generation: generation,
          errorCode: 'request_slot_busy',
        );
      }
      await Future<void>.delayed(const Duration(milliseconds: 5));
    }

    final completer = Completer<BleReceive>();
    final pending = _PendingBleRequest(
      completer: completer,
      generation: generation,
    );
    if (useNext) {
      if (_nextReceive != null && !_nextReceive!.completer.isCompleted) {
        return _timeoutResponse(
          effectMayHaveOccurred: false,
          generation: generation,
          errorCode: 'next_receive_slot_busy',
        );
      }
      _nextReceive = pending;
      _nextReceiveKey = key;
    } else {
      _requestListeners[key] = pending;
    }
    if (timeoutMs > 0) {
      _requestTimeouts[key] = Timer(
        Duration(milliseconds: timeoutMs),
        () => _checkTimeout(key, timeoutMs, generation),
      );
    }

    try {
      final accepted = await sendData(data, lr: side, other: other).timeout(
        const Duration(seconds: 2),
      );
      if (!accepted && !completer.isCompleted) {
        _requestTimeouts.remove(key)?.cancel();
        _requestListeners.remove(key);
        if (_nextReceive == pending) {
          _nextReceive = null;
          _nextReceiveKey = null;
        }
        completer.complete(
          _timeoutResponse(
            effectMayHaveOccurred: false,
            generation: generation,
            errorCode: 'native_write_not_accepted',
          ),
        );
      }
    } on Object {
      if (!completer.isCompleted) {
        _requestTimeouts.remove(key)?.cancel();
        _requestListeners.remove(key);
        if (_nextReceive == pending) {
          _nextReceive = null;
          _nextReceiveKey = null;
        }
        _quarantinedRequestKeys.add(key);
        completer.complete(
          _timeoutResponse(
            effectMayHaveOccurred: true,
            generation: generation,
            errorCode: 'native_write_result_unknown',
          ),
        );
      }
    }

    final response = await completer.future;
    _requestTimeouts.remove(key)?.cancel();
    _requestListeners.remove(key);
    if (_nextReceive == pending) {
      _nextReceive = null;
      _nextReceiveKey = null;
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
    final left = await _requestList(sendList, 'L', timeoutMs: timeoutMs);
    if (!left) {
      return false;
    }
    return _requestList(sendList, 'R', timeoutMs: timeoutMs);
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
    _failPendingRequests(
      'manager_disposed',
      effectMayHaveOccurred: true,
    );
    await _receiveSubscription?.cancel();
    _receiveSubscription = null;
  }
}

extension Uint8ListEx on Uint8List {
  String get hexString =>
      map((int value) => value.toRadixString(16).padLeft(2, '0')).join(' ');
}
