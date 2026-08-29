import 'dart:async';
import 'dart:io';
import 'dart:math';

import 'package:demo_ai_even/ble_manager.dart';
import 'package:demo_ai_even/controllers/evenai_model_controller.dart';
import 'package:demo_ai_even/runtime/privacy_safe_log.dart';
import 'package:demo_ai_even/services/api_services_deepseek.dart';
import 'package:demo_ai_even/services/proto.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:get/get.dart';

class EvenAI {
  EvenAI._();

  static EvenAI? _instance;
  static EvenAI get get => _instance ??= EvenAI._();

  static bool _isRunning = false;
  static bool get isRunning => _isRunning;

  bool isReceivingAudio = false;
  List<int> audioDataBuffer = <int>[];
  Uint8List? audioData;

  File? lc3File;
  File? pcmFile;
  int durationS = 0;

  static const int maxRetry = 10;
  static const int _linesPerPage = 5;
  static const Duration _pageInterval = Duration(seconds: 5);
  static const Duration _singlePageFinalizeDelay = Duration(seconds: 3);
  static const Duration _recordingLimit = Duration(seconds: 30);
  static const Duration _startStopDebounce = Duration(milliseconds: 500);

  static int _currentLine = 0;
  static Timer? _timer;
  static List<String> list = <String>[];
  static List<String> sendReplys = <String>[];
  static bool _isManual = false;

  Timer? _recordingTimer;
  StreamSubscription<dynamic>? _speechSubscription;
  int _lastStartTime = 0;
  int _lastStopTime = 0;
  int retryCount = 0;

  static set isRunning(bool value) {
    _isRunning = value;
    isEvenAIOpen.value = value;
    isEvenAISyncing.value = value;
  }

  static final RxBool isEvenAIOpen = false.obs;
  static final RxBool isEvenAISyncing = false.obs;

  static const String _eventSpeechRecognize = 'eventSpeechRecognize';
  final Stream<dynamic> _eventSpeechRecognizeChannel = const EventChannel(
    _eventSpeechRecognize,
  ).receiveBroadcastStream(_eventSpeechRecognize);

  String combinedText = '';

  static final StreamController<String> _textStreamController =
      StreamController<String>.broadcast();
  static Stream<String> get textStream => _textStreamController.stream;

  static void updateDynamicText(String newText) {
    _textStreamController.add(newText);
  }

  void startListening() {
    combinedText = '';
    unawaited(_speechSubscription?.cancel());
    _speechSubscription = _eventSpeechRecognizeChannel.listen(
      (dynamic event) {
        if (event is Map && event['script'] is String) {
          combinedText = (event['script']! as String).trim();
        }
      },
      onError: (Object error) {
        PrivacySafeLog.event(
          'speech_recognition_error',
          fields: <String, Object?>{'error_type': error.runtimeType.toString()},
        );
      },
    );
  }

  Future<void> toStartEvenAIByOS() async {
    BleManager.get().startSendBeatHeart();
    final now = DateTime.now().millisecondsSinceEpoch;
    if (now - _lastStartTime < _startStopDebounce.inMilliseconds) {
      return;
    }
    _lastStartTime = now;

    clear();
    startListening();
    isReceivingAudio = true;
    isRunning = true;
    _currentLine = 0;

    await BleManager.invokeMethod<void>('startEvenAI');
    final micOpened = await openEvenAIMic();
    if (!micOpened) {
      isEvenAISyncing.value = false;
      await startSendReply('Microphone unavailable.');
      return;
    }
    startRecordingTimer();
    PrivacySafeLog.event('even_ai_started');
  }

  void startRecordingTimer() {
    _recordingTimer?.cancel();
    _recordingTimer = Timer(_recordingLimit, () {
      if (isReceivingAudio) {
        PrivacySafeLog.event('recording_limit_reached');
        clear();
      }
    });
  }

  Future<void> recordOverByOS() async {
    final now = DateTime.now().millisecondsSinceEpoch;
    if (now - _lastStopTime < _startStopDebounce.inMilliseconds) {
      return;
    }
    _lastStopTime = now;

    isReceivingAudio = false;
    _recordingTimer?.cancel();
    _recordingTimer = null;
    await BleManager.invokeMethod<void>('stopEvenAI');
    await Future<void>.delayed(const Duration(seconds: 2));

    if (combinedText.isEmpty) {
      const message = 'No speech recognized.';
      updateDynamicText(message);
      isEvenAISyncing.value = false;
      await startSendReply(message);
      return;
    }

    final apiService = ApiDeepSeekService();
    final answer = await apiService.sendChatRequest(combinedText);
    updateDynamicText('$combinedText\n\n$answer');
    isEvenAISyncing.value = false;
    saveQuestionItem(combinedText, answer);
    await startSendReply(answer);
    PrivacySafeLog.event(
      'even_ai_answer_ready',
      fields: <String, Object?>{
        'question_characters': combinedText.runes.length,
        'answer_characters': answer.runes.length,
      },
    );
  }

  void saveQuestionItem(String title, String content) {
    final controller = Get.find<EvenaiModelController>();
    controller.addItem(title, content);
  }

  int getTotalPages() =>
      list.isEmpty ? 0 : (list.length + _linesPerPage - 1) ~/ _linesPerPage;

  int getCurrentPage() => list.isEmpty ? 0 : (_currentLine ~/ _linesPerPage) + 1;

  Future<void> sendNetworkErrorReply(String text) async {
    _currentLine = 0;
    list = EvenAIDataMethod.measureStringList(text);
    await sendEvenAIReply(_pageText(0), 0x01, 0x60, 0);
    clear();
  }

  Future<void> startSendReply(String text) async {
    _currentLine = 0;
    _isManual = false;
    list = EvenAIDataMethod.measureStringList(text);
    if (list.isEmpty) {
      list = <String>['No response available.'];
    }

    final firstPage = _pageText(0);
    final started = await sendEvenAIReply(firstPage, 0x01, 0x30, 0);
    if (!started) {
      clear();
      return;
    }

    if (getTotalPages() == 1) {
      await Future<void>.delayed(_singlePageFinalizeDelay);
      if (!_isManual && isRunning) {
        await sendEvenAIReply(firstPage, 0x01, 0x40, 0);
      }
      return;
    }
    await updateReplyToOSByTimer();
  }

  Future<void> updateReplyToOSByTimer() async {
    _timer?.cancel();
    _timer = Timer.periodic(_pageInterval, (Timer timer) {
      unawaited(_advanceAutomaticPage());
    });
  }

  Future<void> _advanceAutomaticPage() async {
    if (_isManual || !isRunning) {
      _timer?.cancel();
      _timer = null;
      return;
    }
    final next = _currentLine + _linesPerPage;
    if (next >= list.length) {
      _timer?.cancel();
      _timer = null;
      return;
    }
    _currentLine = next;
    final finalPage = _currentLine + _linesPerPage >= list.length;
    await sendEvenAIReply(
      _pageText(_currentLine),
      0x01,
      finalPage ? 0x40 : 0x30,
      0,
    );
    if (finalPage) {
      _timer?.cancel();
      _timer = null;
    }
  }

  void nextPageByTouchpad() {
    if (!isRunning) {
      return;
    }
    _enterManualMode();
    if (getTotalPages() < 2) {
      unawaited(manualForJustOnePage());
      return;
    }
    final next = _currentLine + _linesPerPage;
    if (next < list.length) {
      _currentLine = next;
      unawaited(updateReplyToOSByManual());
    }
  }

  void lastPageByTouchpad() {
    if (!isRunning) {
      return;
    }
    _enterManualMode();
    if (getTotalPages() < 2) {
      unawaited(manualForJustOnePage());
      return;
    }
    _currentLine = max(0, _currentLine - _linesPerPage);
    unawaited(updateReplyToOSByManual());
  }

  void _enterManualMode() {
    _isManual = true;
    _timer?.cancel();
    _timer = null;
  }

  Future<void> updateReplyToOSByManual() async {
    if (_currentLine < 0 || _currentLine >= list.length) {
      return;
    }
    sendReplys = list.sublist(_currentLine);
    await sendEvenAIReply(_pageText(_currentLine), 0x01, 0x50, 0);
  }

  Future<void> manualForJustOnePage() async {
    if (list.isEmpty) {
      return;
    }
    await sendEvenAIReply(_pageText(0), 0x01, 0x50, 0);
  }

  String _pageText(int start) {
    if (list.isEmpty || start < 0 || start >= list.length) {
      return '';
    }
    final end = min(start + _linesPerPage, list.length);
    final lines = list.sublist(start, end);
    final leadingBlankLines = max(0, (_linesPerPage - lines.length) ~/ 2);
    final prefix = List<String>.filled(leadingBlankLines, '').join('\n');
    return '${prefix.isEmpty ? '' : '$prefix\n'}${lines.join('\n')}\n';
  }

  Future<void> stopEvenAIByOS() async {
    isRunning = false;
    clear();
    await BleManager.invokeMethod<void>('stopEvenAI');
  }

  void clear() {
    isReceivingAudio = false;
    isRunning = false;
    _isManual = false;
    _currentLine = 0;
    _recordingTimer?.cancel();
    _recordingTimer = null;
    _timer?.cancel();
    _timer = null;
    unawaited(_speechSubscription?.cancel());
    _speechSubscription = null;
    audioDataBuffer.clear();
    audioData = null;
    list = <String>[];
    sendReplys = <String>[];
    durationS = 0;
    retryCount = 0;
  }

  Future<bool> openEvenAIMic() async {
    for (var attempt = 1; attempt <= 3; attempt++) {
      final (_, isStartSuccess) = await Proto.micOn(lr: 'R');
      if (isStartSuccess) {
        PrivacySafeLog.event(
          'microphone_opened',
          fields: <String, Object?>{'attempt': attempt},
        );
        return true;
      }
      if (!isReceivingAudio || !isRunning) {
        return false;
      }
      await Future<void>.delayed(const Duration(seconds: 1));
    }
    PrivacySafeLog.event('microphone_open_failed');
    return false;
  }

  Future<bool> sendEvenAIReply(
    String text,
    int type,
    int status,
    int pos,
  ) async {
    if (!isRunning) {
      return false;
    }
    for (var attempt = 0; attempt <= maxRetry; attempt++) {
      final success = await Proto.sendEvenAIData(
        text,
        newScreen: EvenAIDataMethod.transferToNewScreen(type, status),
        pos: pos,
        currentPageNumber: getCurrentPage(),
        maxPageNumber: getTotalPages(),
      );
      if (success) {
        retryCount = 0;
        return true;
      }
      retryCount = attempt + 1;
      if (!isRunning) {
        return false;
      }
    }
    retryCount = 0;
    PrivacySafeLog.event(
      'display_send_failed',
      fields: <String, Object?>{
        'page': getCurrentPage(),
        'page_count': getTotalPages(),
      },
    );
    return false;
  }

  static void dispose() {
    unawaited(_instance?._speechSubscription?.cancel());
    _textStreamController.close();
  }
}

extension EvenAIDataMethod on EvenAI {
  static int transferToNewScreen(int type, int status) => status | type;

  static List<String> measureStringList(String text, [double? maxW]) {
    final maxWidth = maxW ?? 488;
    const fontSize = 21.0;
    final paragraphs = text
        .split('\n')
        .map((String line) => line.trim())
        .where((String line) => line.isNotEmpty)
        .toList(growable: false);
    final result = <String>[];
    const textStyle = TextStyle(fontSize: fontSize);

    for (final paragraph in paragraphs) {
      final textPainter = TextPainter(
        text: TextSpan(text: paragraph, style: textStyle),
        textDirection: TextDirection.ltr,
      )..layout(maxWidth: maxWidth);
      final lineCount = textPainter.computeLineMetrics().length;
      var start = 0;
      for (var index = 0; index < lineCount && start < paragraph.length; index++) {
        final boundary = textPainter.getLineBoundary(TextPosition(offset: start));
        if (boundary.end <= start) {
          break;
        }
        result.add(paragraph.substring(boundary.start, boundary.end).trim());
        start = boundary.end;
      }
    }
    return result;
  }
}
