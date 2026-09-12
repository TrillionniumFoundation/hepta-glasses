enum DeviceEffectDisposition {
  committed,
  rejectedBeforeWrite,
  indeterminate,
}

/// Strongly typed physical-effect completion. A Boolean cannot distinguish a
/// write that definitely did not start from one that may already have reached
/// one or both glasses legs.
final class DeviceEffectResult {
  const DeviceEffectResult._({
    required this.disposition,
    required this.code,
    required this.externalId,
    required this.details,
  });

  factory DeviceEffectResult.committed({
    String code = 'committed',
    String? externalId,
    Map<String, Object?> details = const <String, Object?>{},
  }) =>
      DeviceEffectResult._(
        disposition: DeviceEffectDisposition.committed,
        code: code,
        externalId: externalId,
        details: Map<String, Object?>.unmodifiable(details),
      );

  factory DeviceEffectResult.rejectedBeforeWrite({
    required String code,
    String? externalId,
    Map<String, Object?> details = const <String, Object?>{},
  }) =>
      DeviceEffectResult._(
        disposition: DeviceEffectDisposition.rejectedBeforeWrite,
        code: code,
        externalId: externalId,
        details: Map<String, Object?>.unmodifiable(details),
      );

  factory DeviceEffectResult.indeterminate({
    required String code,
    required String externalId,
    Map<String, Object?> details = const <String, Object?>{},
  }) =>
      DeviceEffectResult._(
        disposition: DeviceEffectDisposition.indeterminate,
        code: code,
        externalId: externalId,
        details: Map<String, Object?>.unmodifiable(details),
      );

  final DeviceEffectDisposition disposition;
  final String code;
  final String? externalId;
  final Map<String, Object?> details;

  bool get committed => disposition == DeviceEffectDisposition.committed;

  bool get retrySafe =>
      disposition == DeviceEffectDisposition.rejectedBeforeWrite;

  bool get effectMayHaveOccurred =>
      disposition != DeviceEffectDisposition.rejectedBeforeWrite;

  Map<String, Object?> toResultJson() => <String, Object?>{
        'effect_disposition': disposition.name,
        'effect_code': code,
        'retry_safe': retrySafe,
        'effect_may_have_occurred': effectMayHaveOccurred,
        if (externalId != null) 'external_id': externalId,
        ...details,
      };

  /// Aggregates concurrently or sequentially attempted legs/packets.
  /// A committed/rejected mix is indeterminate at the aggregate boundary
  /// because a partial physical effect already exists.
  static DeviceEffectResult aggregate(
    Iterable<DeviceEffectResult> outcomes, {
    required String externalId,
    String partialCode = 'partial_effect_indeterminate',
  }) {
    final values = outcomes.toList(growable: false);
    if (values.isEmpty) {
      return DeviceEffectResult.rejectedBeforeWrite(
        code: 'no_effect_attempted',
        externalId: externalId,
      );
    }
    if (values.every((DeviceEffectResult value) => value.committed)) {
      return DeviceEffectResult.committed(
        externalId: externalId,
        details: <String, Object?>{
          'component_count': values.length,
        },
      );
    }
    if (values.every((DeviceEffectResult value) => value.retrySafe)) {
      return DeviceEffectResult.rejectedBeforeWrite(
        code: values.first.code,
        externalId: externalId,
        details: <String, Object?>{
          'component_count': values.length,
          'component_codes': values
              .map((DeviceEffectResult value) => value.code)
              .toList(growable: false),
        },
      );
    }
    return DeviceEffectResult.indeterminate(
      code: partialCode,
      externalId: externalId,
      details: <String, Object?>{
        'component_count': values.length,
        'component_dispositions': values
            .map((DeviceEffectResult value) => value.disposition.name)
            .toList(growable: false),
        'component_codes': values
            .map((DeviceEffectResult value) => value.code)
            .toList(growable: false),
      },
    );
  }
}
