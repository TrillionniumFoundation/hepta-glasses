import 'contracts.dart';

final class DisplayPage {
  const DisplayPage({
    required this.cardId,
    required this.index,
    required this.total,
    required this.lines,
  });

  final String cardId;
  final int index;
  final int total;
  final List<String> lines;

  String get text => lines.join('\n');
}

final class DisplayComposer {
  const DisplayComposer({
    this.maxLines = 5,
    this.maxCharactersPerLine = 24,
  })  : assert(maxLines > 0),
        assert(maxCharactersPerLine > 0);

  final int maxLines;
  final int maxCharactersPerLine;

  List<DisplayPage> compose(DisplayCard card) {
    final lines = <String>[];
    if (card.title.trim().isNotEmpty) {
      lines.addAll(_wrap(card.title.trim()));
    }
    if (card.body.trim().isNotEmpty) {
      for (final paragraph in card.body.split('\n')) {
        final trimmed = paragraph.trim();
        if (trimmed.isNotEmpty) {
          lines.addAll(_wrap(trimmed));
        }
      }
    }
    if (lines.isEmpty) {
      lines.add(' ');
    }

    final pageCount = (lines.length + maxLines - 1) ~/ maxLines;
    return List<DisplayPage>.generate(pageCount, (pageIndex) {
      final start = pageIndex * maxLines;
      final end =
          start + maxLines < lines.length ? start + maxLines : lines.length;
      return DisplayPage(
        cardId: card.cardId,
        index: pageIndex + 1,
        total: pageCount,
        lines: List.unmodifiable(lines.sublist(start, end)),
      );
    }, growable: false);
  }

  List<String> _wrap(String text) {
    final runes = text.runes.toList(growable: false);
    final lines = <String>[];
    for (var start = 0; start < runes.length; start += maxCharactersPerLine) {
      final end = start + maxCharactersPerLine < runes.length
          ? start + maxCharactersPerLine
          : runes.length;
      lines.add(String.fromCharCodes(runes.sublist(start, end)));
    }
    return lines;
  }
}
