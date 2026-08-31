import 'dart:async';
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
  static bool _isManual = false;

  Timer? _recordingTimer;
  StreamSubscription<dynamic>? _speechSubscription;
  Completer<String>? _finalTranscript;
  AssistantSessionToken? _session;
  ModelRequestCancellation? _modelCancellation;
  int _lastStartTime = 0;
  int _lastStopTime = 0;
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

  Future<void> startListening(AssistantSessionToken session) async {
    combinedText = '';
    _finalTranscript = Completer<String>();
    final previous = _speechSubscription;
    _speechSubscription = null;
    await previous?.cancel();
    _speechSubscription = _eventSpeechRecognizeChannel.listen(
      (dynamic event) {
        if (!_isCurrent(session)) {
          return;
        }
        if (event is Map &&
            event['script'] is String &&
            event['is_final'] == true &&
            event['generation'] == session.generation) {
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

    await clear();
    final session = HeptaRuntime.current.sessions.begin();
    _session = session;
    await startListening(session);
    isReceivingAudio = true;
    isRunning = true;
    _currentLine = 0;

    try {
      await BleManager.invokeMethod<void>('startEvenAI', <String, Object?>{
        'generation': session.generation,
      });
      final micOpened = await openEvenAIMic(session);
      if (!_isCurrent(session)) {
        return;
      }
      if (!micOpened) {
        HeptaRuntime.current.sessions.fail(session, 'microphone_unavailable');
        isEvenAISyncing.value = false;
        updateDynamicText('Microphone unavailable.');
        await startSendReply('Microphone unavailable.', session: session);
        await _stopNativeAssistant(session);
        await clear(cancelSession: false);
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
      HeptaRuntime.current.sessions.fail(session, 'assistant_start_failed');
      await _stopNativeAssistant(session);
      await clear(cancelSession: false);
      isEvenAISyncing.value = false;
      updateDynamicText('Voice assistant is unavailable on this platform.');
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
    if (!await _stopNativeAssistant(session)) {
      HeptaRuntime.current.sessions.fail(session, 'speech_stop_failed');
      isEvenAISyncing.value = false;
      updateDynamicText('Speech recognition could not be finalized.');
      await clear(cancelSession: false);
      return;
    }
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
      return;
    }

    HeptaRuntime.current.sessions.transition(
      session,
      AssistantSessionState.thinking,
    );
    String answer;
    final cancellation = ModelRequestCancellation();
    _modelCancellation = cancellation;
    try {
      answer = await ModelGatewayRegistry.current
          .answer(
            question: combinedText,
            taskId: session.sessionId,
            cancellation: cancellation,
          )
          .timeout(
            _modelTimeout,
            onTimeout: () {
              cancellation.cancel('model_deadline_exceeded');
              throw TimeoutException('model_deadline_exceeded');
            },
          );
    } on TimeoutException {
      answer = 'AI service timed out.';
    } on ModelGatewayException catch (error) {
      answer = error.code == 'model_request_cancelled'
          ? 'AI request cancelled.'
          : 'AI service unavailable (${error.code}).';
    } on Object {
      answer = 'AI service unavailable.';
    } finally {
      if (identical(_modelCancellation, cancellation)) {
        _modelCancellation = null;
      }
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
    await clear();
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
      if (_isCurrent(active)) {
        HeptaRuntime.current.sessions.fail(
          active,
          'initial_display_not_acknowledged',
        );
        await clear(cancelSession: false);
      }
      return;
    }

    if (getTotalPages() == 1) {
      await Future<void>.delayed(_singlePageFinalizeDelay);
      if (!_isManual && isRunning && _isCurrent(active)) {
        final completed = await sendEvenAIReply(
          firstPage,
          0x01,
          0x40,
          0,
          session: active,
        );
        if (completed && _isCurrent(active)) {
          HeptaRuntime.current.sessions.complete(active);
        } else if (_isCurrent(active)) {
          HeptaRuntime.current.sessions.fail(
            active,
            'final_display_not_acknowledged',
          );
          await clear(cancelSession: false);
        }
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
    final previousLine = _currentLine;
    try {
      _currentLine = next;
      final finalPage = _currentLine + _linesPerPage >= list.length;
      final delivered = await sendEvenAIReply(
        _pageText(_currentLine),
        0x01,
        finalPage ? 0x40 : 0x30,
        0,
        session: session,
      );
      if (!delivered && _isCurrent(session)) {
        _currentLine = previousLine;
        HeptaRuntime.current.sessions.fail(
          session,
          'page_display_not_acknowledged',
        );
        _timer?.cancel();
        _timer = null;
        await clear(cancelSession: false);
      } else if (finalPage) {
        _timer?.cancel();
        _timer = null;
        if (_isCurrent(session)) {
          HeptaRuntime.current.sessions.complete(session);
        }
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
      unawaited(_sendManualPage(session, next));
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
    unawaited(_sendManualPage(session, max(0, _currentLine - _linesPerPage)));
  }

  Future<void> _sendManualPage(
    AssistantSessionToken session,
    int targetLine,
  ) async {
    if (_pageSendInFlight || !_isCurrent(session)) {
      return;
    }
    final previousLine = _currentLine;
    _pageSendInFlight = true;
    _currentLine = targetLine;
    try {
      final delivered = await updateReplyToOSByManual(session: session);
      if (!delivered && _isCurrent(session) && _currentLine == targetLine) {
        _currentLine = previousLine;
        HeptaRuntime.current.sessions.fail(
          session,
          'manual_display_not_acknowledged',
        );
        await clear(cancelSession: false);
      }
    } finally {
      _pageSendInFlight = false;
    }
  }

  void _enterManualMode() {
    _isManual = true;
    _timer?.cancel();
    _timer = null;
  }

  Future<bool> updateReplyToOSByManual({AssistantSessionToken? session}) async {
    final active = session ?? _session;
    if (active == null ||
        !_isCurrent(active) ||
        _currentLine < 0 ||
        _currentLine >= list.length) {
      return false;
    }
    return sendEvenAIReply(
      _pageText(_currentLine),
      0x01,
      0x50,
      0,
      session: active,
    );
  }

  Future<bool> manualForJustOnePage({AssistantSessionToken? session}) async {
    final active = session ?? _session;
    if (active == null || !_isCurrent(active) || list.isEmpty) {
      return false;
    }
    final delivered = await sendEvenAIReply(
      _pageText(0),
      0x01,
      0x50,
      0,
      session: active,
    );
    if (!delivered && _isCurrent(active)) {
      HeptaRuntime.current.sessions.fail(
        active,
        'manual_display_not_acknowledged',
      );
      await clear(cancelSession: false);
    }
    return delivered;
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
      await _stopNativeAssistant(session);
    }
    await clear(cancelSession: false);
  }

  Future<bool> _stopNativeAssistant(AssistantSessionToken session) async {
    try {
      await BleManager.invokeMethod<void>('stopEvenAI', <String, Object?>{
        'generation': session.generation,
      });
      return true;
    } on Object catch (error) {
      PrivacySafeLog.event(
        'even_ai_native_stop_failed',
        fields: <String, Object?>{
          'generation': session.generation,
          'error_type': error.runtimeType.toString(),
        },
      );
      return false;
    }
  }

  Future<void> clear({bool cancelSession = true}) async {
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
    _modelCancellation?.cancel('session_cleared');
    _modelCancellation = null;
    combinedText = '';
    list = <String>[];
    isReceivingAudio = false;
    isRunning = false;
    _isManual = false;
    _currentLine = 0;
    _recordingTimer?.cancel();
    _recordingTimer = null;
    _timer?.cancel();
    _timer = null;
    final subscription = _speechSubscription;
    _speechSubscription = null;
    await subscription?.cancel();
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
      for (
        var index = 0;
        index < lineCount && start < paragraph.length;
        index++
      ) {
        final boundary = textPainter.getLineBoundary(
          TextPosition(offset: start),
        );
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
