import 'package:demo_ai_even/runtime/assistant_session.dart';
import 'package:demo_ai_even/runtime/clock.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('new session generation cancels the prior session and fences callbacks',
      () {
    final clock = MutableClock(DateTime.utc(2026, 8, 30));
    final coordinator = AssistantSessionCoordinator(clock: clock);
    final first = coordinator.begin(sessionId: 'session-1');
    coordinator.transition(first, AssistantSessionState.recording);

    final second = coordinator.begin(sessionId: 'session-2');

    expect(coordinator.isCurrent(first), isFalse);
    expect(coordinator.isCurrent(second), isTrue);
    expect(
      () => coordinator.transition(first, AssistantSessionState.finalizingSpeech),
      throwsStateError,
    );
  });

  test('assistant lifecycle reaches completed only through valid transitions',
      () {
    final coordinator = AssistantSessionCoordinator(
      clock: MutableClock(DateTime.utc(2026, 8, 30)),
    );
    final session = coordinator.begin(sessionId: 'session-1');
    coordinator.transition(session, AssistantSessionState.recording);
    coordinator.transition(session, AssistantSessionState.finalizingSpeech);
    coordinator.transition(session, AssistantSessionState.thinking);
    coordinator.transition(session, AssistantSessionState.rendering);
    coordinator.complete(session);

    expect(coordinator.current?.state, AssistantSessionState.completed);
    expect(
      () => coordinator.transition(session, AssistantSessionState.rendering),
      throwsStateError,
    );
  });
}
