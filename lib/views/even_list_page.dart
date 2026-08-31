import 'package:demo_ai_even/controllers/evenai_model_controller.dart';
import 'package:demo_ai_even/services/evenai.dart';
import 'package:flutter/material.dart';
import 'package:get/get.dart';

class EvenAIListPage extends StatefulWidget {
  const EvenAIListPage({super.key});

  @override
  State<EvenAIListPage> createState() => _EvenAIListPageState();
}

class _EvenAIListPageState extends State<EvenAIListPage> {
  late final EvenaiModelController controller;

  @override
  void initState() {
    super.initState();
    controller = Get.find<EvenaiModelController>();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(
          title: const Text('History', style: TextStyle(fontSize: 20)),
        ),
        body: Obx(() {
          if (controller.items.isEmpty && !EvenAI.isEvenAISyncing.value) {
            return const Center(
              child: Padding(
                padding: EdgeInsets.all(24),
                child: Text(
                  'Press and hold left TouchBar to engage Even AI.',
                  style: TextStyle(color: Colors.grey),
                  textAlign: TextAlign.center,
                ),
              ),
            );
          }
          return ListView.separated(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
            itemCount: controller.items.length,
            separatorBuilder: (BuildContext context, int index) =>
                const SizedBox(height: 12),
            itemBuilder: (BuildContext context, int index) {
              final expanded = controller.selectedIndex.value == index;
              final item = controller.items[index];
              return Semantics(
                button: true,
                label: item.title,
                child: InkWell(
                  borderRadius: BorderRadius.circular(8),
                  onTap: () {
                    if (expanded) {
                      controller.deselectItem();
                    } else {
                      controller.selectItem(index);
                    }
                  },
                  child: AnimatedSize(
                    duration: const Duration(milliseconds: 160),
                    alignment: Alignment.topCenter,
                    child: Container(
                      width: double.infinity,
                      padding: const EdgeInsets.all(16),
                      decoration: BoxDecoration(
                        color: const Color(0xFFFEF991).withValues(alpha: 0.2),
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: <Widget>[
                          Text(
                            item.title,
                            style: Theme.of(context).textTheme.titleMedium,
                          ),
                          if (expanded) ...<Widget>[
                            const SizedBox(height: 12),
                            SelectableText(
                              item.content,
                              style: Theme.of(context).textTheme.bodyMedium,
                            ),
                          ],
                        ],
                      ),
                    ),
                  ),
                ),
              );
            },
          );
        }),
      );
}
