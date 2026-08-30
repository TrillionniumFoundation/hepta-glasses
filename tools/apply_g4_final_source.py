#!/usr/bin/env python3
"""Apply the final deterministic native-session and transport fixes."""
from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(relative: str, before: str, after: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    count = text.count(before)
    if count != 1:
        raise RuntimeError(f"{relative}: expected one pre-image, found {count}")
    path.write_text(text.replace(before, after, 1), encoding="utf-8")


def main() -> None:
    replace_once(
        "ios/Runner/BluetoothManager.swift",
        '''    func attach(channel: FlutterMethodChannel) {
        self.channel = channel
    }
''',
        '''    func attach(channel: FlutterMethodChannel) {
        self.channel = channel
    }

    func beginAudioSession() {
        pcmConverter.reset()
    }
''',
    )
    replace_once(
        "ios/Runner/BluetoothManager.swift",
        '''            if data[1] == 0 {
                pcmConverter.reset()
            }
            let compressed = data.subdata(in: 2..<data.count)
''',
        '''            let compressed = data.subdata(in: 2..<data.count)
''',
    )
    replace_once(
        "ios/Runner/AppDelegate.swift",
        '''                guard SpeechStreamRecognizer.shared.startRecognition(
                    identifier: "EN",
                    generation: generation
                ) else {
''',
        '''                self.blueInstance.beginAudioSession()
                guard SpeechStreamRecognizer.shared.startRecognition(
                    identifier: "EN",
                    generation: generation
                ) else {
''',
    )
    replace_once(
        "android/app/src/main/kotlin/com/example/demo_ai_even/bluetooth/BleManager.kt",
        '''        connectionGeneration += 1
        readyAddresses.clear()
''',
        '''        connectionGeneration += 1
        intentionalDisconnectAddresses.clear()
        readyAddresses.clear()
''',
    )
    replace_once(
        "lib/adapters/even_g1/even_g1_transport.dart",
        '''    final future = _sendOnce(
      side: side,
      bytes: bytes,
      timeout: timeout,
      idempotencyKey: idempotencyKey,
      fingerprint: fingerprint,
    );
    _attemptFingerprints[idempotencyKey] = fingerprint;
    _inFlight[idempotencyKey] = future;
    future.whenComplete(() {
      if (identical(_inFlight[idempotencyKey], future)) {
        _inFlight.remove(idempotencyKey);
        _attemptFingerprints.remove(idempotencyKey);
      }
    });
    return future;
''',
        '''    final operation = _sendOnce(
      side: side,
      bytes: bytes,
      timeout: timeout,
      idempotencyKey: idempotencyKey,
      fingerprint: fingerprint,
    );
    late final Future<TransportAck> tracked;
    tracked = operation.whenComplete(() {
      if (identical(_inFlight[idempotencyKey], tracked)) {
        _inFlight.remove(idempotencyKey);
        _attemptFingerprints.remove(idempotencyKey);
      }
    });
    _attemptFingerprints[idempotencyKey] = fingerprint;
    _inFlight[idempotencyKey] = tracked;
    return tracked;
''',
    )
    Path(__file__).unlink()
    print("final G4 source fixes applied")


if __name__ == "__main__":
    main()
