import 'dart:async';
import 'dart:io';
import 'dart:math';

import 'package:demo_ai_even/ble_manager.dart';
import 'package:demo_ai_even/controllers/evenai_model_controller.dart';
import 'package:demo_ai_even/runtime/assistant_session.dart';
import 'package:demo_ai_even/runtime/contracts.dart';
import 'package:demo_ai_even/runtime/hepta_runtime.dart';
import 'package:demo_ai_even/runtime/model_gateway.dart';
import 'package:demo_ai_even/runtime/privacy_safe_log.dart';
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

  static const int _linesPerPage = 5;
  static const Duration _pageInterval = Duration(seconds: 5);
  static const Duration _singlePageFinalizeDelay = Duration(seconds: 3);
  static const Duration _recordingLimit = Duration(seconds: 30);
  static const Duration _startStopDebounce = Duration(milliseconds: 500);
  static const Duration _finalTranscriptTimeout = Duration(seconds: 3);
  static const Duration _modelTimeout = Duration(seconds: 60);

  static int _currentLine = 0;
  static Timer? _timer;
  static List<String> list = <String>[];
  static List<String> sendReplys = <String>[];
  static bool _isManual = false;

  Timer? _recordingTimer;
  StreamSubscription<dynamic>? _speechSubscription;
  Completer<String>? _finalTranscript;
  AssistantSessionToken? _session;
  int _lastStartTime = 0;
  int _lastStopTime = 0;
  int retryCount = 0;
  bool _pageSendInFlight = false;

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

  void startListening(AssistantSessionToken session) {
    combinedText = '';
    _finalTranscript = Completer<String>();
    unawaited(_speechSubscription?.cancel());
    _speechSubscription = _eventSpeechRecognizeChannel.listen(
      (dynamic event) {
        if (!_isCurrent(session)) {
          return;
        }
        if (event is Map && event['script'] is String) {
          combinedText = (event['script']! as String).trim();
          final completer = _finalTranscript;
          if (completer != null && !completer.isCompleted) {
            completer.complete(combinedText);
          }
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
    final session = HeptaRuntime.current.sessions.begin();
    _session = session;
    startListening(session);
    isReceivingAudio = true;
    isRunning = true;
    _currentLine = 0;

    try {
      await BleManager.invokeMethod<void>('startEvenAI');
      final micOpened = await openEvenAIMic(session);
      if (!_isCurrent(session)) {
        return;
      }
      if (!micOpened) {
        HeptaRuntime.current.sessions.fail(session, 'microphone_unavailable');
        isEvenAISyncing.value = false;
        await startSendReply('Microphone unavailable.', session: session);
        return;
      }
      HeptaRuntime.current.sessions.transition(
        session,
        AssistantSessionState.recording,
      );
      startRecordingTimer(session);
      PrivacySafeLog.event(
        'even_ai_started',
        fields: <String, Object?>{'generation': session.generation},
      );
    } on Object catch (error) {
      HeptaRuntime.current.sessions.fail(
        session,
        'assistant_start_failed',
      );
      PrivacySafeLog.event(
        'even_ai_start_failed',
        fields: <String, Object?>{'error_type': error.runtimeType.toString()},
      );
    }
  }

  void startRecordingTimer(AssistantSessionToken session) {
    _recordingTimer?.cancel();
    _recordingTimer = Timer(_recordingLimit, () {
      if (isReceivingAudio && _isCurrent(session)) {
        PrivacySafeLog.event('recording_limit_reached');
        unawaited(stopEvenAIByOS(reason: 'recording_limit_reached'));
      }
    });
  }

  Future<void> recordOverByOS() async {
    final session = _session;
    if (session == null || !_isCurrent(session)) {
      return;
    }
    final now = DateTime.now().millisecondsSinceEpoch;
    if (now - _lastStopTime < _startStopDebounce.inMilliseconds) {
      return;
    }
    _lastStopTime = now;

    isReceivingAudio = false;
    _recordingTimer?.cancel();
    _recordingTimer = null;
    try {
      HeptaRuntime.current.sessions.transition(
        session,
        AssistantSessionState.finalizingSpeech,
      );
    } on StateError {
      return;
    }
    await BleManager.invokeMethod<void>('stopEvenAI');
    final transcript = await _awaitFinalTranscript(session);
    if (!_isCurrent(session)) {
      return;
    }
    combinedText = transcript.trim();

    if (combinedText.isEmpty) {
      const message = 'No speech recognized.';
      HeptaRuntime.current.sessions.transition(
        session,
        AssistantSessionState.thinking,
      );
      HeptaRuntime.current.sessions.transition(
        session,
        AssistantSessionState.rendering,
      );
      updateDynamicText(message);
      isEvenAISyncing.value = false;
      await startSendReply(message, session: session);
      if (_isCurrent(session)) {
        HeptaRuntime.current.sessions.complete(session);
      }
      return;
    }

    HeptaRuntime.current.sessions.transition(
      session,
      AssistantSessionState.thinking,
    );
    String answer;
    try {
      answer = await ModelGatewayRegistry.current
          .answer(question: combinedText, taskId: session.sessionId)
          .timeout(_modelTimeout);
    } on TimeoutException {
      answer = 'AI service timed out.';
    } on ModelGatewayException catch (error) {
      answer = 'AI service unavailable (${error.code}).';
    } on Object {
      answer = 'AI service unavailable.';
    }
    if (!_isCurrent(session)) {
      return;
    }

    HeptaRuntime.current.sessions.transition(
      session,
      AssistantSessionState.rendering,
    );
    updateDynamicText('$combinedText\n\n$answer');
    isEvenAISyncing.value = false;
    saveQuestionItem(combinedText, answer);
    await startSendReply(answer, session: session);
    if (_isCurrent(session)) {
      HeptaRuntime.current.sessions.complete(session);
    }
    PrivacySafeLog.event(
      'even_ai_answer_ready',
      fields: <String, Object?>{
        'generation': session.generation,
        'question_characters': combinedText.runes.length,
        'answer_characters': answer.runes.length,
      },
    );
  }

  Future<String> _awaitFinalTranscript(AssistantSessionToken session) async {
    final completer = _finalTranscript;
    if (completer == null) {
      return combinedText;
    }
    try {
      final transcript = await completer.future.timeout(
        _finalTranscriptTimeout,
        onTimeout: () => combinedText,
      );
      return _isCurrent(session) ? transcript : '';
    } on Object {
      return _isCurrent(session) ? combinedText : '';
    }
  }

  void saveQuestionItem(String title, String content) {
    final controller = Get.find<EvenaiModelController>();
    controller.addItem(title, content);
  }

  int getTotalPages() =>
      list.isEmpty ? 0 : (list.length + _linesPerPage - 1) ~/ _linesPerPage;

  int getCurrentPage() =>
      list.isEmpty ? 0 : (_currentLine ~/ _linesPerPage) + 1;

  Future<void> sendNetworkErrorReply(String text) async {
    final session = _session;
    if (session == null || !_isCurrent(session)) {
      return;
    }
    _currentLine = 0;
    list = EvenAIDataMethod.measureStringList(text);
    await sendEvenAIReply(_pageText(0), 0x01, 0x60, 0, session: session);
    clear();
  }

  Future<void> startSendReply(
    String text, {
    AssistantSessionToken? session,
  }) async {
    final active = session ?? _session;
    if (active == null || !_isCurrent(active)) {
      return;
    }
    _currentLine = 0;
    _isManual = false;
    list = EvenAIDataMethod.measureStringList(text);
    if (list.isEmpty) {
      list = <String>['No response available.'];
    }

    final firstPage = _pageText(0);
    final started = await sendEvenAIReply(
      firstPage,
      0x01,
      0x30,
      0,
      session: active,
    );
    if (!started || !_isCurrent(active)) {
      return;
    }

    if (getTotalPages() == 1) {
      await Future<void>.delayed(_singlePageFinalizeDelay);
      if (!_isManual && isRunning && _isCurrent(active)) {
        await sendEvenAIReply(
          firstPage,
          0x01,
          0x40,
          0,
          session: active,
        );
      }
      return;
    }
    updateReplyToOSByTimer(active);
  }

  void updateReplyToOSByTimer(AssistantSessionToken session) {
    _timer?.cancel();
    _timer = Timer.periodic(_pageInterval, (Timer timer) {
      unawaited(_advanceAutomaticPage(session));
    });
  }

  Future<void> _advanceAutomaticPage(AssistantSessionToken session) async {
    if (_pageSendInFlight || _isManual || !isRunning || !_isCurrent(session)) {
      if (_isManual || !isRunning || !_isCurrent(session)) {
        _timer?.cancel();
        _timer = null;
      }
      return;
    }
    final next = _currentLine + _linesPerPage;
    if (next >= list.length) {
      _timer?.cancel();
      _timer = null;
      return;
    }
    _pageSendInFlight = true;
    try {
      _currentLine = next;
      final finalPage = _currentLine + _linesPerPage >= list.length;
      await sendEvenAIReply(
        _pageText(_currentLine),
        0x01,
        finalPage ? 0x40 : 0x30,
        0,
        session: session,
      );
      if (finalPage) {
        _timer?.cancel();
        _timer = null;
      }
    } finally {
      _pageSendInFlight = false;
    }
  }

  void nextPageByTouchpad() {
    final session = _session;
    if (!isRunning || session == null || !_isCurrent(session)) {
      return;
    }
    _enterManualMode();
    if (getTotalPages() < 2) {
      unawaited(manualForJustOnePage(session: session));
      return;
    }
    final next = _currentLine + _linesPerPage;
    if (next < list.length) {
      _currentLine = next;
      unawaited(updateReplyToOSByManual(session: session));
    }
  }

  void lastPageByTouchpad() {
    final session = _session;
    if (!isRunning || session == null || !_isCurrent(session)) {
      return;
    }
    _enterManualMode();
    if (getTotalPages() < 2) {
      unawaited(manualForJustOnePage(session: session));
      return;
    }
    _currentLine = max(0, _currentLine - _linesPerPage);
    unawaited(updateReplyToOSByManual(session: session));
  }

  void _enterManualMode() {
    _isManual = true;
    _timer?.cancel();
    _timer = null;
  }

  Future<void> updateReplyToOSByManual({
    AssistantSessionToken? session,
  }) async {
    final active = session ?? _session;
    if (active == null ||
        !_isCurrent(active) ||
        _currentLine < 0 ||
        _currentLine >= list.length) {
      return;
    }
    sendReplys = list.sublist(_currentLine);
    await sendEvenAIReply(
      _pageText(_currentLine),
      0x01,
      0x50,
      0,
      session: active,
    );
  }

  Future<void> manualForJustOnePage({
    AssistantSessionToken? session,
  }) async {
    final active = session ?? _session;
    if (active == null || !_isCurrent(active) || list.isEmpty) {
      return;
    }
    await sendEvenAIReply(
      _pageText(0),
      0x01,
      0x50,
      0,
      session: active,
    );
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

  Future<void> stopEvenAIByOS({String reason = 'user_cancelled'}) async {
    final session = _session;
    if (session != null && _isCurrent(session)) {
      HeptaRuntime.current.sessions.cancel(session, reason: reason);
    }
    clear(cancelSession: false);
    await BleManager.invokeMethod<void>('stopEvenAI');
  }

  void clear({bool cancelSession = true}) {
    final session = _session;
    if (cancelSession &&
        session != null &&
        HeptaRuntime.isInitialized &&
        _isCurrent(session)) {
      HeptaRuntime.current.sessions.cancel(session, reason: 'session_cleared');
    }
    final transcript = _finalTranscript;
    if (transcript != null && !transcript.isCompleted) {
      transcript.complete(combinedText);
    }
    _finalTranscript = null;
    _session = null;
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
    _pageSendInFlight = false;
  }

  Future<bool> openEvenAIMic(AssistantSessionToken session) async {
    for (var attempt = 1; attempt <= 3; attempt++) {
      if (!_isCurrent(session)) {
        return false;
      }
      final (_, isStartSuccess) = await Proto.micOn(lr: 'R');
      if (!_isCurrent(session)) {
        return false;
      }
      if (isStartSuccess) {
        PrivacySafeLog.event(
          'microphone_opened',
          fields: <String, Object?>{'attempt': attempt},
        );
        return true;
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
    int pos, {
    required AssistantSessionToken session,
  }) async {
    if (!isRunning || !_isCurrent(session)) {
      return false;
    }
    final receipt = await HeptaRuntime.current.displayText(
      session: session,
      text: text,
      newScreen: EvenAIDataMethod.transferToNewScreen(type, status),
      position: pos,
      currentPageNumber: getCurrentPage(),
      maxPageNumber: getTotalPages(),
    );
    if (!_isCurrent(session)) {
      return false;
    }
    retryCount = receipt.status == ToolReceiptStatus.succeeded ? 0 : 1;
    if (receipt.status == ToolReceiptStatus.succeeded) {
      return true;
    }
    PrivacySafeLog.event(
      receipt.status == ToolReceiptStatus.indeterminate
          ? 'display_reconciliation_required'
          : 'display_send_failed',
      fields: <String, Object?>{
        'page': getCurrentPage(),
        'page_count': getTotalPages(),
        'status': receipt.status.name,
      },
    );
    return false;
  }

  bool _isCurrent(AssistantSessionToken session) =>
      HeptaRuntime.isInitialized &&
      HeptaRuntime.current.sessions.isCurrent(session);

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
      for (var index = 0;
          index < lineCount && start < paragraph.length;
          index++) {
        final boundary =
            textPainter.getLineBoundary(TextPosition(offset: start));
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
