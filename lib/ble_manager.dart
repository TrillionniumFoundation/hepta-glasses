import 'dart:async';

import 'package:demo_ai_even/app.dart';
import 'package:demo_ai_even/runtime/ble_request_slot.dart';
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
  static BleManager get() => _instance ??= BleManager._();

  static const String methodSend = 'send';
  static const String _eventBleReceive = 'eventBleReceive';
  static const MethodChannel _channel = MethodChannel('method.bluetooth');

  final Stream<BleReceive> eventBleReceive =
      const EventChannel(_eventBleReceive)
          .receiveBroadcastStream(_eventBleReceive)
          .map(
            (dynamic value) =>
                BleReceive.fromMap(value as Map<dynamic, dynamic>),
          );

  StreamSubscription<BleReceive>? _receiveSubscription;
  static const Duration _heartbeatInterval = Duration(seconds: 8);

  Timer? beatHeartTimer;
  bool _heartbeatInFlight = false;

  final List<Map<String, String>> pairedGlasses = <Map<String, String>>[];
  bool isConnected = false;
  String connectionStatus = 'Not connected';
  int _connectionGeneration = 0;
  bool isLeftConnected = false;
  bool isRightConnected = false;
  final StreamController<BleConnectionSnapshot> _connectionController =
      StreamController<BleConnectionSnapshot>.broadcast();

  int get connectionGeneration => _connectionGeneration;
  Stream<BleConnectionSnapshot> get connectionSnapshots =>
      _connectionController.stream;
  BleConnectionSnapshot get connectionSnapshot => BleConnectionSnapshot(
        leftConnected: isLeftConnected,
        rightConnected: isRightConnected,
        generation: _connectionGeneration,
      );

  void _publishConnectionSnapshot() {
    if (!_connectionController.isClosed) {
      _connectionController.add(connectionSnapshot);
    }
  }

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
      rethrow;
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
      rethrow;
    }
  }

  Future<void> connectToGlasses(String deviceName) async {
    beatHeartTimer?.cancel();
    beatHeartTimer = null;
    _failPendingRequests('connection_replaced', effectMayHaveOccurred: true);
    connectionStatus = 'Connecting...';
    isLeftConnected = false;
    isRightConnected = false;
    isConnected = false;
    _publishConnectionSnapshot();
    onStatusChanged?.call();
    try {
      await _channel.invokeMethod<void>('connectToGlasses', <String, Object?>{
        'deviceName': deviceName,
      });
    } on PlatformException catch (error) {
      connectionStatus = 'Not connected';
      _publishConnectionSnapshot();
      onStatusChanged?.call();
      PrivacySafeLog.event(
        'ble_connect_failed',
        fields: <String, Object?>{'code': error.code},
      );
      rethrow;
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
      rethrow;
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
    _requestRegistry.clearQuarantine();
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
    isLeftConnected = values['left_connected'] == true;
    isRightConnected = values['right_connected'] == true;
    isConnected = isLeftConnected && isRightConnected;
    connectionStatus = isConnected
        ? 'Connected: \n$leftName \n$rightName'
        : 'Connection not ready';
    _publishConnectionSnapshot();
    onStatusChanged?.call();
    if (isConnected) {
      startSendBeatHeart();
    } else {
      beatHeartTimer?.cancel();
      beatHeartTimer = null;
    }
    PrivacySafeLog.event(
      'ble_connected',
      fields: <String, Object?>{'generation': _connectionGeneration},
    );
  }

  void startSendBeatHeart() {
    beatHeartTimer?.cancel();
    beatHeartTimer = null;
    if (!isConnected || _heartbeatInFlight) {
      return;
    }
    beatHeartTimer = Timer(
      _heartbeatInterval,
      () => unawaited(_sendHeartbeat()),
    );
  }

  Future<void> _sendHeartbeat() async {
    if (_heartbeatInFlight || !isConnected) {
      return;
    }
    _heartbeatInFlight = true;
    try {
      var success = await Proto.sendHeartBeat();
      for (var attempt = 0; !success && attempt < 2 && isConnected; attempt++) {
        success = await Proto.sendHeartBeat();
      }
      if (!success) {
        PrivacySafeLog.event(
          'ble_heartbeat_failed',
          fields: <String, Object?>{'generation': _connectionGeneration},
        );
      }
    } finally {
      _heartbeatInFlight = false;
      if (isConnected) {
        startSendBeatHeart();
      }
    }
  }

  void _onGlassesConnecting(dynamic arguments) {
    final generation = _generationFrom(arguments);
    if (_isStaleGeneration(generation)) {
      return;
    }
    _adoptGeneration(generation);
    connectionStatus = 'Connecting...';
    isLeftConnected = false;
    isRightConnected = false;
    isConnected = false;
    _publishConnectionSnapshot();
    onStatusChanged?.call();
  }

  void _onGlassesDisconnected(dynamic arguments) {
    final generation = _generationFrom(arguments);
    if (_isStaleGeneration(generation)) {
      return;
    }
    _adoptGeneration(generation);
    final values = arguments is Map ? arguments : const <Object?, Object?>{};
    isLeftConnected = values['left_connected'] == true;
    isRightConnected = values['right_connected'] == true;
    isConnected = isLeftConnected && isRightConnected;
    connectionStatus = isConnected
        ? 'Connected'
        : (isLeftConnected || isRightConnected
            ? 'Degraded connection'
            : 'Not connected');
    _publishConnectionSnapshot();
    beatHeartTimer?.cancel();
    beatHeartTimer = null;
    _failPendingRequests('device_disconnected', effectMayHaveOccurred: true);
    _requestRegistry.clearQuarantine();
    onStatusChanged?.call();
    PrivacySafeLog.event(
      'ble_disconnected',
      fields: <String, Object?>{
        'generation': _connectionGeneration,
        'left_connected': isLeftConnected,
        'right_connected': isRightConnected,
      },
    );
  }

  void _onPairedGlassesFound(Map<String, String> deviceInfo) {
    final channelNumber = deviceInfo['channelNumber'];
    if (channelNumber == null || channelNumber.isEmpty) {
      return;
    }
    final existingIndex = pairedGlasses.indexWhere(
      (Map<String, String> glasses) =>
          glasses['channelNumber'] == channelNumber,
    );
    final immutable = Map<String, String>.unmodifiable(deviceInfo);
    if (existingIndex < 0) {
      pairedGlasses.add(immutable);
    } else {
      pairedGlasses[existingIndex] = immutable;
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

    if (response.lr != 'L' && response.lr != 'R') {
      PrivacySafeLog.event(
        'ble_response_side_invalid',
        fields: <String, Object?>{'command': command},
      );
      return;
    }

    final generation =
        response.generation > 0 ? response.generation : _connectionGeneration;
    final key = BleRequestKey(
      generation: generation,
      side: response.lr,
      command: command,
    );

    if (_requestRegistry.observeLateResponse(key)) {
      PrivacySafeLog.event(
        'ble_late_response_observed',
        fields: <String, Object?>{
          'generation': generation,
          'side': response.lr,
          'command': command,
        },
      );
      return;
    }

    final pending = _requestRegistry.take(key);
    _requestTimeouts.remove(key)?.cancel();
    if (pending == null || pending.completer.isCompleted) {
      PrivacySafeLog.event(
        'ble_unsolicited_response',
        fields: <String, Object?>{
          'generation': generation,
          'side': response.lr,
          'command': command,
        },
      );
      return;
    }
    if (pending.generation == generation || pending.generation == 0) {
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
  }

  String getConnectionStatus() => connectionStatus;

  List<Map<String, String>> getPairedGlasses() =>
      List<Map<String, String>>.unmodifiable(pairedGlasses);

  static final BleRequestRegistry<BleReceive> _requestRegistry =
      BleRequestRegistry<BleReceive>();
  static final Map<BleRequestKey, Timer> _requestTimeouts =
      <BleRequestKey, Timer>{};

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

  static void _startAckTimeout(
    BleRequestKey key,
    BleRequestSlot<BleReceive> pending,
    int requestedTimeoutMs,
  ) {
    final timeoutMs = requestedTimeoutMs > 0 ? requestedTimeoutMs : 1000;
    _requestTimeouts.remove(key)?.cancel();
    if (pending.completer.isCompleted) {
      return;
    }
    _requestTimeouts[key] = Timer(Duration(milliseconds: timeoutMs), () {
      if (!_requestRegistry.quarantineIfOwned(key, pending)) {
        return;
      }
      _requestTimeouts.remove(key)?.cancel();
      if (!pending.completer.isCompleted) {
        pending.completer.complete(
          _timeoutResponse(
            effectMayHaveOccurred: true,
            generation: pending.generation,
            errorCode: 'ack_timeout_after_native_write',
          ),
        );
      }
      PrivacySafeLog.event(
        'ble_request_timeout',
        fields: <String, Object?>{
          'timeout_ms': timeoutMs,
          'generation': pending.generation,
          'side': key.side,
          'command': key.command,
        },
      );
    });
  }

  void _failPendingRequests(
    String reason, {
    required bool effectMayHaveOccurred,
  }) {
    final entries = _requestRegistry.takeAllPending();
    for (final timer in _requestTimeouts.values) {
      timer.cancel();
    }
    _requestTimeouts.clear();
    for (final entry in entries) {
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
    PrivacySafeLog.event(
      'ble_pending_requests_failed',
      fields: <String, Object?>{
        'reason': reason,
        'request_count': entries.length,
      },
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
          !_isSideReady(lr ?? Proto.lR())) {
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
    if (data.isEmpty) {
      return false;
    }
    final parameters = <String, dynamic>{'data': data, ...?other};
    if (lr != null) {
      if (lr != 'L' && lr != 'R') {
        return false;
      }
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
    if (side != 'L' && side != 'R') {
      return _timeoutResponse(
        effectMayHaveOccurred: false,
        generation: generation,
        errorCode: 'invalid_side',
      );
    }
    if (!_isSideReady(side)) {
      return _timeoutResponse(
        effectMayHaveOccurred: false,
        generation: generation,
        errorCode: 'side_not_ready',
      );
    }

    final key = BleRequestKey(
      generation: generation,
      side: side,
      command: data[0],
    );
    if (_requestRegistry.isQuarantined(key)) {
      return _timeoutResponse(
        effectMayHaveOccurred: true,
        generation: generation,
        errorCode: 'request_slot_quarantined',
      );
    }

    final slotDeadline = DateTime.now().add(const Duration(seconds: 3));
    while (_requestRegistry.contains(key)) {
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

    if (manager._connectionGeneration != generation || !_isSideReady(side)) {
      return _timeoutResponse(
        effectMayHaveOccurred: false,
        generation: generation,
        errorCode: 'connection_changed_before_write',
      );
    }

    final pending = BleRequestSlot<BleReceive>(
      completer: Completer<BleReceive>(),
      generation: generation,
    );
    // `useNext` is retained for source compatibility. Both legacy modes now
    // reserve the same exact response owner.
    if (!_requestRegistry.reserve(key, pending)) {
      return _timeoutResponse(
        effectMayHaveOccurred: _requestRegistry.isQuarantined(key),
        generation: generation,
        errorCode: _requestRegistry.isQuarantined(key)
            ? 'request_slot_quarantined'
            : 'request_slot_busy',
      );
    }

    try {
      final accepted = await sendData(
        data,
        lr: side,
        other: other,
      ).timeout(const Duration(seconds: 2));
      if (!accepted && !pending.completer.isCompleted) {
        _requestRegistry.releaseIfOwned(key, pending);
        pending.completer.complete(
          _timeoutResponse(
            effectMayHaveOccurred: false,
            generation: generation,
            errorCode: 'native_write_not_accepted',
          ),
        );
      } else if (accepted && !pending.completer.isCompleted) {
        _startAckTimeout(key, pending, timeoutMs);
      }
    } on Object catch (error) {
      if (!pending.completer.isCompleted) {
        _requestTimeouts.remove(key)?.cancel();
        final quarantined = _requestRegistry.quarantineIfOwned(key, pending);
        if (quarantined) {
          pending.completer.complete(
            _timeoutResponse(
              effectMayHaveOccurred: true,
              generation: generation,
              errorCode: 'native_write_result_unknown',
            ),
          );
        }
      }
      PrivacySafeLog.event(
        'ble_native_write_error',
        fields: <String, Object?>{
          'generation': generation,
          'side': side,
          'error_type': error.runtimeType.toString(),
        },
      );
    }

    final response = await pending.completer.future;
    _requestTimeouts.remove(key)?.cancel();
    _requestRegistry.releaseIfOwned(key, pending);
    return response;
  }

  static bool _isSideReady(String side) {
    final manager = get();
    return side == 'L'
        ? manager.isLeftConnected
        : side == 'R'
            ? manager.isRightConnected
            : false;
  }

  static bool isBothConnected() =>
      get().isLeftConnected && get().isRightConnected;

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
    beatHeartTimer = null;
    _heartbeatInFlight = false;
    _failPendingRequests('manager_disposed', effectMayHaveOccurred: true);
    _requestRegistry.clearQuarantine();
    await _receiveSubscription?.cancel();
    _receiveSubscription = null;
    await _connectionController.close();
  }
}

extension Uint8ListEx on Uint8List {
  String get hexString =>
      map((int value) => value.toRadixString(16).padLeft(2, '0')).join(' ');
}
