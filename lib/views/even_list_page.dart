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
              child: Text(
                'Press and hold left TouchBar to engage Even AI.',
                style: TextStyle(color: Colors.grey),
                textAlign: TextAlign.center,
              ),
            );
          }
          return ListView.builder(
            padding: const EdgeInsets.fromLTRB(16, 4, 16, 16),
            itemCount: controller.items.length,
            itemBuilder: (BuildContext context, int index) => GestureDetector(
              key: ValueKey<String>('history-item-$index'),
              onTap: () {
                if (controller.selectedIndex.value == index) {
                  controller.deselectItem();
                } else {
                  controller.selectItem(index);
                }
              },
              child: controller.selectedIndex.value == index
                  ? _buildItemDetail(index)
                  : _buildItem(index),
            ),
          );
        }),
      );

  Widget _buildItem(int index) {
    final item = controller.items[index];
    return Container(
      alignment: Alignment.centerLeft,
      decoration: BoxDecoration(
        color: const Color(0xFFFEF991).withValues(alpha: 0.2),
        borderRadius: BorderRadius.circular(5),
      ),
      margin: const EdgeInsets.symmetric(vertical: 8),
      padding: const EdgeInsets.all(16),
      child: Text(
        item.title,
        style: const TextStyle(fontSize: 20),
      ),
    );
  }

  Widget _buildItemDetail(int index) {
    final item = controller.items[index];
    return Container(
      key: ValueKey<String>('history-detail-$index'),
      decoration: BoxDecoration(
        color: const Color(0xFFFEF991).withValues(alpha: 0.2),
        borderRadius: BorderRadius.circular(5),
      ),
      margin: const EdgeInsets.symmetric(vertical: 8),
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(
            item.title,
            style: const TextStyle(fontSize: 20),
          ),
          const SizedBox(height: 12),
          Text(
            item.content,
            style: const TextStyle(fontSize: 15),
          ),
        ],
      ),
    );
  }
}
