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

  testWidgets('history items expand without invalid flex parent data',
      (WidgetTester tester) async {
    final controller = Get.put(EvenaiModelController());
    controller.addItem('Question', 'Answer');

    await tester.pumpWidget(
      const MaterialApp(home: EvenAIListPage()),
    );
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
