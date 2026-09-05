import 'package:demo_ai_even/runtime/contracts.dart';
import 'package:demo_ai_even/runtime/display_composer.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('display composer creates bounded deterministic pages', () {
    const composer = DisplayComposer(maxLines: 2, maxCharactersPerLine: 4);
    final card = DisplayCard(
      cardId: 'card-1',
      taskId: 'task-1',
      kind: DisplayCardKind.answer,
      title: 'Hepta',
      body: '智能眼镜操作系统',
    );

    final pages = composer.compose(card);
    expect(pages, isNotEmpty);
    expect(pages.every((DisplayPage page) => page.lines.length <= 2), isTrue);
    expect(pages.last.total, pages.length);
    expect(pages.first.index, 1);
  });
}
