import 'package:demo_ai_even/controllers/evenai_model_controller.dart';
import 'package:demo_ai_even/services/evenai.dart';
import 'package:demo_ai_even/views/even_list_page.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:get/get.dart';

void main() {
  setUp(() {
    Get.testMode = true;
    Get.put(EvenaiModelController());
    EvenAI.isEvenAISyncing.value = false;
  });
  tearDown(() async {
    await Get.deleteAll(force: true);
    EvenAI.isEvenAISyncing.value = false;
  });
  testWidgets('history list renders and expands without parent-data errors',
      (WidgetTester tester) async {
    Get.find<EvenaiModelController>().addItem('Question', 'Answer');
    await tester.pumpWidget(const MaterialApp(home: EvenAIListPage()));
    await tester.pump();
    expect(find.text('Question'), findsOneWidget);
    expect(find.text('Answer'), findsNothing);
    expect(tester.takeException(), isNull);
    await tester.tap(find.text('Question'));
    await tester.pump();
    expect(find.text('Answer'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
