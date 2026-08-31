import 'dart:async';

import 'clock.dart';

enum AssistantSessionState {
  idle,
  acquiringAudio,
  recording,
  finalizingSpeech,
  thinking,
  rendering,
  completed,
  cancelled,
  failed,
}

final class AssistantSessionToken {
  const AssistantSessionToken({
    required this.sessionId,
    required this.generation,
  });

  final String sessionId;
  final int generation;
}

final class AssistantSessionSnapshot {
  const AssistantSessionSnapshot({
    required this.token,
    required this.state,
    required this.updatedAt,
    this.reason,
  });

  final AssistantSessionToken token;
  final AssistantSessionState state;
  final DateTime updatedAt;
  final String? reason;

  bool get terminal => <AssistantSessionState>{
        AssistantSessionState.completed,
        AssistantSessionState.cancelled,
        AssistantSessionState.failed,
      }.contains(state);
}

final class AssistantSessionCoordinator {
  AssistantSessionCoordinator({Clock clock = const SystemClock()})
      : _clock = clock;

  final Clock _clock;
  final StreamController<AssistantSessionSnapshot> _controller =
      StreamController<AssistantSessionSnapshot>.broadcast();
  int _generation = 0;
  AssistantSessionSnapshot? _current;

  static final Map<AssistantSessionState, Set<AssistantSessionState>>
      _allowedTransitions = <AssistantSessionState, Set<AssistantSessionState>>{
    AssistantSessionState.acquiringAudio: <AssistantSessionState>{
      AssistantSessionState.recording,
      AssistantSessionState.cancelled,
      AssistantSessionState.failed,
    },
    AssistantSessionState.recording: <AssistantSessionState>{
      AssistantSessionState.finalizingSpeech,
      AssistantSessionState.cancelled,
      AssistantSessionState.failed,
    },
    AssistantSessionState.finalizingSpeech: <AssistantSessionState>{
      AssistantSessionState.thinking,
      AssistantSessionState.cancelled,
      AssistantSessionState.failed,
    },
    AssistantSessionState.thinking: <AssistantSessionState>{
      AssistantSessionState.rendering,
      AssistantSessionState.cancelled,
      AssistantSessionState.failed,
    },
    AssistantSessionState.rendering: <AssistantSessionState>{
      AssistantSessionState.completed,
      AssistantSessionState.cancelled,
      AssistantSessionState.failed,
    },
    AssistantSessionState.idle: <AssistantSessionState>{},
    AssistantSessionState.completed: <AssistantSessionState>{},
    AssistantSessionState.cancelled: <AssistantSessionState>{},
    AssistantSessionState.failed: <AssistantSessionState>{},
  };

  Stream<AssistantSessionSnapshot> get snapshots => _controller.stream;

  AssistantSessionSnapshot? get current => _current;

  AssistantSessionToken begin({String? sessionId}) {
    final previous = _current;
    if (previous != null && !previous.terminal) {
      _emit(
        AssistantSessionSnapshot(
          token: previous.token,
          state: AssistantSessionState.cancelled,
          updatedAt: _clock.now(),
          reason: 'superseded_by_new_session',
        ),
      );
    }
    _generation++;
    final token = AssistantSessionToken(
      sessionId: sessionId ??
          'assistant-${_clock.now().microsecondsSinceEpoch}-$_generation',
      generation: _generation,
    );
    _emit(
      AssistantSessionSnapshot(
        token: token,
        state: AssistantSessionState.acquiringAudio,
        updatedAt: _clock.now(),
      ),
    );
    return token;
  }

  bool isCurrent(AssistantSessionToken token) =>
      _current?.token.sessionId == token.sessionId &&
      _current?.token.generation == token.generation;

  AssistantSessionSnapshot transition(
    AssistantSessionToken token,
    AssistantSessionState next, {
    String? reason,
  }) {
    final current = _requireCurrent(token);
    if (current.state == next) {
      return current;
    }
    final allowed =
        _allowedTransitions[current.state] ?? const <AssistantSessionState>{};
    if (!allowed.contains(next)) {
      throw StateError(
        'Invalid assistant transition ${current.state.name} -> ${next.name}.',
      );
    }
    final updated = AssistantSessionSnapshot(
      token: token,
      state: next,
      updatedAt: _clock.now(),
      reason: reason,
    );
    _emit(updated);
    return updated;
  }

  void cancel(AssistantSessionToken token, {String reason = 'cancelled'}) {
    if (!isCurrent(token) || _current!.terminal) {
      return;
    }
    transition(token, AssistantSessionState.cancelled, reason: reason);
  }

  void fail(AssistantSessionToken token, String reason) {
    if (!isCurrent(token) || _current!.terminal) {
      return;
    }
    transition(token, AssistantSessionState.failed, reason: reason);
  }

  void complete(AssistantSessionToken token) {
    if (!isCurrent(token) || _current!.terminal) {
      return;
    }
    transition(token, AssistantSessionState.completed);
  }

  AssistantSessionSnapshot _requireCurrent(AssistantSessionToken token) {
    if (!isCurrent(token)) {
      throw StateError('Stale assistant session generation.');
    }
    return _current!;
  }

  void _emit(AssistantSessionSnapshot snapshot) {
    _current = snapshot;
    if (!_controller.isClosed) {
      _controller.add(snapshot);
    }
  }

  Future<void> dispose() => _controller.close();
}
