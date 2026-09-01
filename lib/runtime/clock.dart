abstract interface class Clock {
  DateTime now();
}

final class SystemClock implements Clock {
  const SystemClock();

  @override
  DateTime now() => DateTime.now().toUtc();
}

final class MutableClock implements Clock {
  MutableClock(DateTime initial) : _value = initial.toUtc();

  DateTime _value;

  @override
  DateTime now() => _value;

  void advance(Duration duration) {
    _value = _value.add(duration);
  }

  void set(DateTime value) {
    _value = value.toUtc();
  }
}
