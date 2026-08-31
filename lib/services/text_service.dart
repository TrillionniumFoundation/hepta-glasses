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

  RuntimeEffectScope? _scope;
  int _generation = 0;
  int? _sendInFlightGeneration;

  Future<bool> startSendText(String text) async {
    clear();
    final generation = _generation;
    list = EvenAIDataMethod.measureStringList(text);
    if (list.isEmpty) {
      return false;
    }

    isRunning = true;
    _scope = HeptaRuntime.current.beginEffectScope('manual-text');
    _currentLine = 0;
    final success = await _sendCurrentPage(generation);
    if (!_isCurrent(generation)) {
      return false;
    }
    if (!success) {
      clear();
      return false;
    }
    if (getTotalPages() > 1) {
      _scheduleNextPage(generation);
    } else {
      isRunning = false;
      _scope = null;
    }
    return true;
  }

  Future<bool> _doSendText(
    String text,
    int type,
    int status,
    int position,
    int generation,
  ) async {
    final scope = _scope;
    if (!_isCurrent(generation) ||
        scope == null ||
        _sendInFlightGeneration == generation) {
      return false;
    }
    _sendInFlightGeneration = generation;
    try {
      final receipt = await HeptaRuntime.current.displayTextInScope(
        scope: scope,
        text: text,
        newScreen: EvenAIDataMethod.transferToNewScreen(type, status),
        position: position,
        currentPageNumber: getCurrentPage(),
        maxPageNumber: getTotalPages(),
      );
      return _isCurrent(generation) &&
          receipt.status == ToolReceiptStatus.succeeded;
    } finally {
      if (_sendInFlightGeneration == generation) {
        _sendInFlightGeneration = null;
      }
    }
  }

  void _scheduleNextPage(int generation) {
    _timer?.cancel();
    _timer = Timer(_pageInterval, () => unawaited(_advancePage(generation)));
  }

  Future<void> _advancePage(int generation) async {
    if (!_isCurrent(generation) || _sendInFlightGeneration == generation) {
      return;
    }
    final next = _currentLine + _linesPerPage;
    if (next >= list.length) {
      _finish(generation);
      return;
    }
    final previousLine = _currentLine;
    _currentLine = next;
    final success = await _sendCurrentPage(generation);
    if (!_isCurrent(generation)) {
      return;
    }
    if (!success) {
      _currentLine = previousLine;
      clear();
      return;
    }
    if (_currentLine + _linesPerPage >= list.length) {
      _finish(generation);
    } else {
      _scheduleNextPage(generation);
    }
  }

  Future<bool> _sendCurrentPage(int generation) {
    final text = _pageText(_currentLine);
    return _doSendText(text, 0x01, 0x70, 0, generation);
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

  bool _isCurrent(int generation) => isRunning && generation == _generation;

  void _finish(int generation) {
    if (!_isCurrent(generation)) {
      return;
    }
    _timer?.cancel();
    _timer = null;
    isRunning = false;
    _scope = null;
  }

  void clear() {
    _generation++;
    isRunning = false;
    _currentLine = 0;
    _timer?.cancel();
    _timer = null;
    list = <String>[];
    _scope = null;
    _sendInFlightGeneration = null;
  }
}
