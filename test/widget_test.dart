import 'package:demo_ai_even/main.dart' as application;
import 'package:demo_ai_even/runtime/contracts.dart';
import 'package:demo_ai_even/runtime/display_composer.dart';
import 'package:flutter/material.dart';
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

  testWidgets('durable-startup failure exposes no action authority', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(const application.FailClosedStartupApp());

    expect(
      find.textContaining('Device and assistant actions remain disabled'),
      findsOneWidget,
    );
    expect(find.byType(ElevatedButton), findsNothing);
    expect(find.byType(FilledButton), findsNothing);
    expect(find.byType(OutlinedButton), findsNothing);
    expect(find.byType(TextButton), findsNothing);
    expect(find.byType(IconButton), findsNothing);
    expect(tester.takeException(), isNull);
  });
}
