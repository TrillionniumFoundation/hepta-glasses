import 'package:demo_ai_even/controllers/evenai_model_controller.dart';
import 'package:demo_ai_even/services/evenai.dart';
import 'package:demo_ai_even/views/even_list_page.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:get/get.dart';

void main() {
  setUp(() {
    Get.testMode = true;
    EvenAI.isEvenAISyncing.value = false;
  });

  tearDown(Get.reset);

  test('assistant history is opt-in and defaults to disabled', () {
    final controller = EvenaiModelController();

    expect(controller.historyEnabled.value, isFalse);
    expect(controller.addItem('Question', 'Answer'), isFalse);
    expect(controller.items, isEmpty);
  });

  test(
    'disabling assistant history deletes retained content and selection',
    () {
      final controller = EvenaiModelController();

      controller.setHistoryEnabled(true);
      expect(controller.addItem('Question', 'Answer'), isTrue);
      controller.selectItem(0);
      expect(controller.items, hasLength(1));
      expect(controller.selectedIndex.value, 0);

      controller.setHistoryEnabled(false);

      expect(controller.historyEnabled.value, isFalse);
      expect(controller.items, isEmpty);
      expect(controller.selectedIndex.value, isNull);
    },
  );

  testWidgets('history consent control gates and clears UI history', (
    WidgetTester tester,
  ) async {
    final controller = Get.put(EvenaiModelController());

    await tester.pumpWidget(const MaterialApp(home: EvenAIListPage()));
    expect(
      find.byKey(const ValueKey<String>('history-disabled')),
      findsOneWidget,
    );

    await tester.tap(
      find.byKey(const ValueKey<String>('history-consent-switch')),
    );
    await tester.pump();
    expect(controller.historyEnabled.value, isTrue);
    expect(
      find.byKey(const ValueKey<String>('history-enabled-empty')),
      findsOneWidget,
    );

    expect(controller.addItem('Question', 'Answer'), isTrue);
    await tester.pump();
    expect(find.text('Question'), findsOneWidget);

    await tester.tap(
      find.byKey(const ValueKey<String>('history-consent-switch')),
    );
    await tester.pump();
    expect(controller.historyEnabled.value, isFalse);
    expect(controller.items, isEmpty);
    expect(find.text('Question'), findsNothing);
  });

  testWidgets('history items expand without invalid flex parent data', (
    WidgetTester tester,
  ) async {
    final controller = Get.put(EvenaiModelController());
    controller.setHistoryEnabled(true);
    expect(controller.addItem('Question', 'Answer'), isTrue);

    await tester.pumpWidget(const MaterialApp(home: EvenAIListPage()));
    expect(tester.takeException(), isNull);
    expect(find.text('Question'), findsOneWidget);
    expect(find.text('Answer'), findsNothing);

    await tester.tap(find.byKey(const ValueKey<String>('history-item-0')));
    await tester.pump();

    expect(tester.takeException(), isNull);
    expect(
      find.byKey(const ValueKey<String>('history-detail-0')),
      findsOneWidget,
    );
    expect(find.text('Answer'), findsOneWidget);
  });
}
