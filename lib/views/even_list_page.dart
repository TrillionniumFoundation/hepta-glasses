import 'package:demo_ai_even/controllers/evenai_model_controller.dart';
import 'package:demo_ai_even/services/evenai.dart';
import 'package:flutter/material.dart';
import 'package:get/get.dart';

class EvenAIListPage extends StatelessWidget {
  const EvenAIListPage({super.key});

  @override
  Widget build(BuildContext context) {
    final controller = Get.find<EvenaiModelController>();
    return Scaffold(
      appBar:
          AppBar(title: const Text('History', style: TextStyle(fontSize: 20))),
      body: Obx(() {
        if (controller.items.isEmpty && !EvenAI.isEvenAISyncing.value) {
          return const Center(
              child: Padding(
                  padding: EdgeInsets.all(24),
                  child: Text('Press and hold left TouchBar to engage Even AI.',
                      style: TextStyle(color: Colors.grey),
                      textAlign: TextAlign.center)));
        }
        return ListView.builder(
          padding: const EdgeInsets.fromLTRB(16, 4, 16, 16),
          itemCount: controller.items.length,
          itemBuilder: (BuildContext context, int index) {
            final item = controller.items[index];
            final expanded = controller.selectedIndex.value == index;
            return Card(
              key: ValueKey<String>(
                  'history-${item.createdTime.microsecondsSinceEpoch}-$index'),
              margin: const EdgeInsets.symmetric(vertical: 8),
              color: const Color(0x33FEF991),
              clipBehavior: Clip.antiAlias,
              child: Semantics(
                button: true,
                label: item.title,
                child: InkWell(
                  onTap: () => expanded
                      ? controller.deselectItem()
                      : controller.selectItem(index),
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: <Widget>[
                          Text(item.title,
                              style: Theme.of(context).textTheme.titleLarge),
                          if (expanded) ...<Widget>[
                            const SizedBox(height: 12),
                            Text(item.content,
                                style: Theme.of(context).textTheme.bodyMedium)
                          ],
                        ]),
                  ),
                ),
              ),
            );
          },
        );
      }),
    );
  }
}
