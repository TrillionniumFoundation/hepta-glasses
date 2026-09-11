import 'package:demo_ai_even/models/evenai_model.dart';
import 'package:get/get.dart';

class EvenaiModelController extends GetxController {
  final items = <EvenaiModel>[].obs;
  final selectedIndex = Rxn<int>();

  /// Transcript and answer history is sensitive and therefore opt-in.
  ///
  /// The current implementation is process-memory only. It intentionally
  /// defaults to disabled on every application start; disabling it immediately
  /// deletes every retained item.
  final historyEnabled = false.obs;

  bool addItem(String title, String content) {
    if (!historyEnabled.value) {
      return false;
    }
    final newItem = EvenaiModel(
      title: title,
      content: content,
      createdTime: DateTime.now(),
    );
    items.insert(0, newItem);
    return true;
  }

  void setHistoryEnabled(bool enabled) {
    historyEnabled.value = enabled;
    if (!enabled) {
      clearItems();
    }
  }

  void removeItem(int index) {
    if (index < 0 || index >= items.length) {
      return;
    }
    items.removeAt(index);
    if (selectedIndex.value == index) {
      selectedIndex.value = null;
    } else if (selectedIndex.value != null && selectedIndex.value! > index) {
      selectedIndex.value = selectedIndex.value! - 1;
    }
  }

  void clearItems() {
    items.clear();
    selectedIndex.value = null;
  }

  void selectItem(int index) {
    if (index < 0 || index >= items.length) {
      selectedIndex.value = null;
      return;
    }
    selectedIndex.value = index;
  }

  void deselectItem() {
    selectedIndex.value = null;
  }

  @override
  void onClose() {
    clearItems();
    historyEnabled.value = false;
    super.onClose();
  }
}
