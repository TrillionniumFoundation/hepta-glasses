import 'dart:async';
import 'dart:math';

import 'package:demo_ai_even/runtime/contracts.dart';
import 'package:demo_ai_even/runtime/hepta_runtime.dart';
import 'package:demo_ai_even/services/evenai.dart';

class TextService {
  TextService._();

  static TextService? _instance;
  static TextService get get => _instance ??= TextService._();

  static const int _linesPerPage = 5;
  static const Duration _pageInterval = Duration(seconds: 8);

  static bool isRunning = false;
  static int _currentLine = 0;
  static Timer? _timer;
  static List<String> list = <String>[];
  static List<String> sendReplys = <String>[];

  RuntimeEffectScope? _scope;
  bool _sendInFlight = false;

  Future<bool> startSendText(String text) async {
    clear();
    list = EvenAIDataMethod.measureStringList(text);
    if (list.isEmpty) {
      return false;
    }

    isRunning = true;
    _scope = HeptaRuntime.current.beginEffectScope('manual-text');
    _currentLine = 0;
    final success = await _sendCurrentPage();
    if (!success) {
      clear();
      return false;
    }
    if (getTotalPages() > 1) {
      _timer = Timer.periodic(_pageInterval, (_) {
        unawaited(_advancePage());
      });
    }
    return true;
  }

  Future<bool> doSendText(
    String text,
    int type,
    int status,
    int position,
  ) async {
    final scope = _scope;
    if (!isRunning || scope == null || _sendInFlight) {
      return false;
    }
    _sendInFlight = true;
    try {
      final receipt = await HeptaRuntime.current.displayTextInScope(
        scope: scope,
        text: text,
        newScreen: EvenAIDataMethod.transferToNewScreen(type, status),
        position: position,
        currentPageNumber: getCurrentPage(),
        maxPageNumber: getTotalPages(),
      );
      return receipt.status == ToolReceiptStatus.succeeded;
    } finally {
      _sendInFlight = false;
    }
  }

  Future<void> _advancePage() async {
    if (!isRunning || _sendInFlight) {
      return;
    }
    final next = _currentLine + _linesPerPage;
    if (next >= list.length) {
      _timer?.cancel();
      _timer = null;
      isRunning = false;
      return;
    }
    _currentLine = next;
    final success = await _sendCurrentPage();
    if (!success || _currentLine + _linesPerPage >= list.length) {
      _timer?.cancel();
      _timer = null;
      isRunning = false;
    }
  }

  Future<bool> _sendCurrentPage() {
    final text = _pageText(_currentLine);
    return doSendText(text, 0x01, 0x70, 0);
  }

  String _pageText(int start) {
    if (start < 0 || start >= list.length) {
      return '';
    }
    final end = min(start + _linesPerPage, list.length);
    final lines = list.sublist(start, end);
    final leadingBlankLines = max(0, (_linesPerPage - lines.length) ~/ 2);
    final prefix = List<String>.filled(leadingBlankLines, '').join('\n');
    return '${prefix.isEmpty ? '' : '$prefix\n'}${lines.join('\n')}\n';
  }

  int getTotalPages() =>
      list.isEmpty ? 0 : (list.length + _linesPerPage - 1) ~/ _linesPerPage;

  int getCurrentPage() =>
      list.isEmpty ? 0 : (_currentLine ~/ _linesPerPage) + 1;

  Future<void> stopTextSendingByOS() async {
    clear();
  }

  void clear() {
    isRunning = false;
    _currentLine = 0;
    _timer?.cancel();
    _timer = null;
    list = <String>[];
    sendReplys = <String>[];
    _scope = null;
    _sendInFlight = false;
  }
}
