import 'dart:convert';
import 'dart:developer' as developer;

final class PrivacySafeLog {
  PrivacySafeLog._();

  static const Set<String> _sensitiveKeys = <String>{
    'audio',
    'answer',
    'body',
    'content',
    'message',
    'prompt',
    'question',
    'text',
    'token',
    'transcript',
  };

  static void event(
    String name, {
    Map<String, Object?> fields = const <String, Object?>{},
  }) {
    final safe = <String, Object?>{};
    for (final entry in fields.entries) {
      if (_sensitiveKeys.contains(entry.key.toLowerCase())) {
        continue;
      }
      final value = entry.value;
      if (value == null || value is num || value is bool) {
        safe[entry.key] = value;
      } else if (value is String) {
        safe[entry.key] = value.length <= 64
            ? value
            : '${value.substring(0, 64)}…';
      }
    }
    developer.log(
      jsonEncode(<String, Object?>{'event': name, 'fields': safe}),
      name: 'hepta_glasses',
    );
  }
}
