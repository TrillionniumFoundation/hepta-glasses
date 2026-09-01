import 'package:demo_ai_even/runtime/contracts.dart';
import 'package:demo_ai_even/runtime/display_composer.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('AI-native display contract smoke test', () {
    final card = DisplayCard(
      cardId: 'smoke-card',
      taskId: 'smoke-task',
      kind: DisplayCardKind.status,
      title: 'Hepta Glasses',
      body: 'Runtime ready',
    );
    const composer = DisplayComposer();
    final pages = composer.compose(card);

    expect(pages, hasLength(1));
    expect(pages.single.text, contains('Runtime ready'));
  });
}
