#!/usr/bin/env python3
"""One-shot G8 source convergence materializer.

This script is executed only by the branch-scoped bootstrap workflow. It fails
closed when an expected source shape is missing, removes every temporary
write-capable workflow (including itself), and leaves the candidate with the
single read-only CI authority.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REVISION = "2026-08-31-g8"
BOOTSTRAP_WORKFLOW = ROOT / ".github/workflows/g8-source-materialize.yml"


def fail(message: str) -> None:
    raise SystemExit(message)


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content.rstrip() + "\n", encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    count = text.count(old)
    if count != 1:
        fail(f"{path}: expected one replacement, found {count}: {old[:80]!r}")
    write(path, text.replace(old, new, 1))


def regex_replace_once(
    path: str,
    pattern: str,
    replacement: str,
    *,
    flags: int = 0,
) -> None:
    text = read(path)
    updated, count = re.subn(pattern, replacement, text, count=1, flags=flags)
    if count != 1:
        fail(f"{path}: expected one regex replacement, found {count}: {pattern!r}")
    write(path, updated)


def rename_product_identity() -> None:
    text_suffixes = {
        ".dart",
        ".kt",
        ".java",
        ".cpp",
        ".cc",
        ".c",
        ".h",
        ".m",
        ".mm",
        ".gradle",
        ".yaml",
        ".yml",
        ".json",
        ".md",
        ".plist",
        ".pbxproj",
        ".xcconfig",
    }
    excluded_roots = {".git", "build", ".dart_tool"}
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in text_suffixes:
            continue
        if any(part in excluded_roots for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="strict")
        updated = text
        updated = updated.replace("package:demo_ai_even/", "package:hepta_glasses/")
        updated = updated.replace("name: demo_ai_even", "name: hepta_glasses")
        updated = updated.replace(
            "com.example.demo_ai_even", "org.trillionnium.heptaglasses"
        )
        updated = updated.replace(
            "Java_com_example_demo_1ai_1even_cpp_Cpp",
            "Java_org_trillionnium_heptaglasses_cpp_Cpp",
        )
        if updated != text:
            path.write_text(updated, encoding="utf-8")

    plist = read("ios/Runner/Info.plist")
    plist = plist.replace(
        "<string>Demo Ai Even</string>", "<string>Hepta Glasses</string>"
    )
    plist = plist.replace(
        "<string>demo_ai_even</string>", "<string>hepta_glasses</string>"
    )
    write("ios/Runner/Info.plist", plist)


def unify_ble_request_slot() -> None:
    path = "lib/ble_manager.dart"

    regex_replace_once(
        path,
        r"""\n    final next = _nextReceive;\n    if \(_nextReceiveKey == key && next != null && !next\.completer\.isCompleted\) \{\n.*?\n      _nextReceiveKey = null;\n    \}\n""",
        "\n",
        flags=re.S,
    )
    replace_once(
        path,
        """  static final Set<String> _quarantinedRequestKeys = <String>{};
  static _PendingBleRequest? _nextReceive;
  static String? _nextReceiveKey;
""",
        """  static final Set<String> _quarantinedRequestKeys = <String>{};
""",
    )
    regex_replace_once(
        path,
        r"""\n    final next = _nextReceive;\n    if \(_nextReceiveKey == key && next != null && !next\.completer\.isCompleted\) \{\n.*?\n      _nextReceiveKey = null;\n    \}\n""",
        "\n",
        flags=re.S,
    )
    replace_once(
        path,
        """    final next = _nextReceive;
    if (next != null && !next.completer.isCompleted) {
      next.completer.complete(
        _timeoutResponse(
          effectMayHaveOccurred: effectMayHaveOccurred,
          generation: next.generation,
          errorCode: reason,
        ),
      );
    }
    _nextReceive = null;
    _nextReceiveKey = null;
""",
        "",
    )
    regex_replace_once(
        path,
        r"""    if \(useNext\) \{\n      if \(_nextReceive != null && !_nextReceive!\.completer\.isCompleted\) \{\n.*?\n    \} else \{\n      _requestListeners\[key\] = pending;\n    \}\n""",
        """    // `useNext` is retained for source compatibility. Response ownership is
    // intentionally unified: one generation/side/command key has exactly one
    // pending request and one timeout.
    _requestListeners[key] = pending;
""",
        flags=re.S,
    )
    text = read(path)
    cleanup = """        if (_nextReceive == pending) {
          _nextReceive = null;
          _nextReceiveKey = null;
        }
"""
    if text.count(cleanup) != 2:
        fail(f"{path}: expected two pre-completion next-slot cleanup blocks")
    text = text.replace(cleanup, "")
    cleanup_final = """    if (_nextReceive == pending) {
      _nextReceive = null;
      _nextReceiveKey = null;
    }
"""
    if text.count(cleanup_final) != 1:
        fail(f"{path}: expected one final next-slot cleanup block")
    text = text.replace(cleanup_final, "")
    if "_nextReceive" in text or "_nextReceiveKey" in text:
        fail(f"{path}: legacy dual-slot symbols remain")
    write(path, text)

    write(
        "test/runtime/ble_request_slot_regression_test.dart",
        r"""
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('BLE response ownership uses one exact request slot', () {
    final source = File('lib/ble_manager.dart').readAsStringSync();

    expect(source, isNot(contains('_nextReceive')));
    expect(source, isNot(contains('_nextReceiveKey')));
    expect(source, contains('_requestListeners[key] = pending;'));
    expect(
      source,
      contains('one generation/side/command key has exactly one'),
    );
  });
}
""",
    )


def harden_android_transport() -> None:
    write(
        "android/app/src/main/kotlin/org/trillionnium/heptaglasses/bluetooth/BoundedWriteQueue.kt",
        r"""
package org.trillionnium.heptaglasses.bluetooth

import java.util.ArrayDeque

internal class BoundedWriteQueue(private val capacity: Int = 128) {
    init {
        require(capacity > 0) { "capacity must be positive" }
    }

    private val queue = ArrayDeque<ByteArray>()

    @Synchronized
    fun offer(data: ByteArray): Boolean {
        if (data.isEmpty() || queue.size >= capacity) return false
        queue.addLast(data.copyOf())
        return true
    }

    @Synchronized
    fun poll(): ByteArray? = queue.pollFirst()

    @Synchronized
    fun clear() {
        queue.clear()
    }

    @Synchronized
    fun size(): Int = queue.size
}
""",
    )
    write(
        "android/app/src/test/kotlin/org/trillionnium/heptaglasses/bluetooth/BoundedWriteQueueTest.kt",
        r"""
package org.trillionnium.heptaglasses.bluetooth

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class BoundedWriteQueueTest {
    @Test
    fun queueIsBoundedAndCopiesPayloads() {
        val queue = BoundedWriteQueue(capacity = 2)
        val first = byteArrayOf(1, 2)

        assertTrue(queue.offer(first))
        first[0] = 9
        assertTrue(queue.offer(byteArrayOf(3)))
        assertFalse(queue.offer(byteArrayOf(4)))
        assertEquals(2, queue.size())
        assertArrayEquals(byteArrayOf(1, 2), queue.poll())
        assertArrayEquals(byteArrayOf(3), queue.poll())
        assertNull(queue.poll())
    }

    @Test
    fun emptyPayloadIsRejectedAndClearIsDeterministic() {
        val queue = BoundedWriteQueue(capacity = 1)

        assertFalse(queue.offer(byteArrayOf()))
        assertTrue(queue.offer(byteArrayOf(7)))
        queue.clear()
        assertEquals(0, queue.size())
        assertNull(queue.poll())
    }
}
""",
    )

    write(
        "android/app/src/main/kotlin/com/example/demo_ai_even/model/BleDevice.kt",
        r"""
package org.trillionnium.heptaglasses.model

import android.annotation.SuppressLint
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCharacteristic
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.util.Log
import org.trillionnium.heptaglasses.bluetooth.BleManager
import org.trillionnium.heptaglasses.bluetooth.BoundedWriteQueue

@SuppressLint("MissingPermission")
data class BleDevice(
    val name: String,
    val address: String,
    var gatt: BluetoothGatt?,
    var writeCharacteristic: BluetoothGattCharacteristic?,
    var isConnect: Boolean,
    val channelNumber: String,
) {
    companion object {
        private const val WRITE_INTERVAL_MS = 8L

        fun createByDevice(
            name: String,
            address: String,
            channelNumber: String,
        ) = BleDevice(name, address, null, null, false, channelNumber)
    }

    private val writeQueue = BoundedWriteQueue(capacity = 128)
    private val mainHandler = Handler(Looper.getMainLooper())

    @Volatile
    private var drainScheduled = false

    fun isLeft() = name.contains("_L_")

    fun isRight() = name.contains("_R_")

    fun sendData(data: ByteArray): Boolean {
        if (data.isEmpty() || !isConnect || gatt == null || writeCharacteristic == null) {
            Log.e(BleManager.LOG_TAG, "$name: GATT is not ready")
            return false
        }
        if (!writeQueue.offer(data)) {
            Log.e(BleManager.LOG_TAG, "$name: bounded write queue rejected data")
            return false
        }
        scheduleDrain()
        return true
    }

    @Synchronized
    private fun scheduleDrain() {
        if (drainScheduled) return
        drainScheduled = true
        mainHandler.post { drainOne() }
    }

    private fun drainOne() {
        val payload = writeQueue.poll()
        if (payload == null) {
            synchronized(this) {
                drainScheduled = false
                if (writeQueue.size() > 0) scheduleDrain()
            }
            return
        }

        if (!writeNow(payload)) {
            writeQueue.clear()
            synchronized(this) {
                drainScheduled = false
            }
            return
        }
        mainHandler.postDelayed({ drainOne() }, WRITE_INTERVAL_MS)
    }

    private fun writeNow(data: ByteArray): Boolean {
        val currentGatt = gatt
        val characteristic = writeCharacteristic
        if (currentGatt == null || characteristic == null || !isConnect) {
            return false
        }
        return try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                currentGatt.writeCharacteristic(
                    characteristic,
                    data,
                    BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE,
                ) == BluetoothGatt.GATT_SUCCESS
            } else {
                @Suppress("DEPRECATION")
                characteristic.writeType =
                    BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE
                @Suppress("DEPRECATION")
                characteristic.value = data
                @Suppress("DEPRECATION")
                currentGatt.writeCharacteristic(characteristic)
            }
        } catch (error: Exception) {
            Log.e(BleManager.LOG_TAG, "$name: write failed", error)
            false
        }
    }

    fun disconnectAndClose() {
        mainHandler.removeCallbacksAndMessages(null)
        writeQueue.clear()
        synchronized(this) {
            drainScheduled = false
        }
        try {
            gatt?.disconnect()
        } catch (error: Exception) {
            Log.w(BleManager.LOG_TAG, "$name: disconnect failed", error)
        }
        try {
            gatt?.close()
        } catch (error: Exception) {
            Log.w(BleManager.LOG_TAG, "$name: close failed", error)
        }
        gatt = null
        writeCharacteristic = null
        isConnect = false
    }
}
""",
    )

    path = "android/app/src/main/kotlin/com/example/demo_ai_even/bluetooth/BleManager.kt"
    replace_once(
        path,
        """    private val readyAddresses: MutableSet<String> = mutableSetOf()
    private val intentionalDisconnectAddresses: MutableSet<String> = mutableSetOf()
""",
        """    private val notificationReadyAddresses: MutableSet<String> = mutableSetOf()
    private val readyAddresses: MutableSet<String> = mutableSetOf()
    private val intentionalDisconnectAddresses: MutableSet<String> = mutableSetOf()
""",
    )
    replace_once(
        path,
        """        intentionalDisconnectAddresses.clear()
        readyAddresses.clear()
""",
        """        intentionalDisconnectAddresses.clear()
        notificationReadyAddresses.clear()
        readyAddresses.clear()
""",
    )
    replace_once(
        path,
        """            if (status != BluetoothGatt.GATT_SUCCESS) {
                handleDisconnected(gatt, "notification_descriptor_failed_$status")
                return
            }
            markReady(gatt)
        }

        @Deprecated("Deprecated in Android 13")
""",
        """            if (status != BluetoothGatt.GATT_SUCCESS) {
                handleDisconnected(gatt, "notification_descriptor_failed_$status")
                return
            }
            notificationReadyAddresses.add(gatt.device.address)
            if (!gatt.requestMtu(251)) {
                handleDisconnected(gatt, "mtu_request_not_started")
            }
        }

        override fun onMtuChanged(gatt: BluetoothGatt, mtu: Int, status: Int) {
            if (!current(gatt)) return
            if (status != BluetoothGatt.GATT_SUCCESS ||
                mtu < 203 ||
                !notificationReadyAddresses.contains(gatt.device.address)
            ) {
                handleDisconnected(gatt, "mtu_contract_failed_${status}_$mtu")
                return
            }
            markReady(gatt)
        }

        @Deprecated("Deprecated in Android 13")
""",
    )
    replace_once(
        path,
        """        readyAddresses.add(address)
        gatt.requestMtu(251)
        gatt.device.createBond()
        if (isLeft) {
            pair.update(leftGatt = gatt, isLeftConnect = true)
            pair.leftDevice?.sendData(byteArrayOf(0xf4.toByte(), 0x01))
        } else {
            pair.update(rightGatt = gatt, isRightConnected = true)
            pair.rightDevice?.sendData(byteArrayOf(0xf4.toByte(), 0x01))
        }
        if (pair.isBothConnected() && readyAddresses.size == 2) {
""",
        """        if (readyAddresses.contains(address)) return

        gatt.device.createBond()
        val initializationAccepted = if (isLeft) {
            pair.update(leftGatt = gatt, isLeftConnect = true)
            pair.leftDevice?.sendData(byteArrayOf(0xf4.toByte(), 0x01)) == true
        } else {
            pair.update(rightGatt = gatt, isRightConnected = true)
            pair.rightDevice?.sendData(byteArrayOf(0xf4.toByte(), 0x01)) == true
        }
        if (!initializationAccepted) {
            handleDisconnected(gatt, "initialization_write_not_accepted")
            return
        }
        readyAddresses.add(address)
        if (pair.isBothConnected() && readyAddresses.size == 2) {
""",
    )
    replace_once(
        path,
        """        readyAddresses.remove(gatt.device.address)
""",
        """        notificationReadyAddresses.remove(gatt.device.address)
        readyAddresses.remove(gatt.device.address)
""",
    )
    replace_once(
        path,
        """        readyAddresses.clear()
        connectedDevice = null
""",
        """        notificationReadyAddresses.clear()
        readyAddresses.clear()
        connectedDevice = null
""",
    )


def harden_ios_speech_finalization() -> None:
    write(
        "ios/Runner/SpeechStreamRecognizer.swift",
        r"""
import AVFoundation
import Speech

final class SpeechStreamRecognizer {
    static let shared = SpeechStreamRecognizer()

    private static let locales: [String: String] = [
        "CN": "zh-CN",
        "EN": "en-US",
        "RU": "ru-RU",
        "KR": "ko-KR",
        "JP": "ja-JP",
        "ES": "es-ES",
        "FR": "fr-FR",
        "DE": "de-DE",
        "NL": "nl-NL",
        "NB": "nb-NO",
        "DA": "da-DK",
        "SV": "sv-SE",
        "FI": "fi-FI",
        "IT": "it-IT",
    ]

    private var recognizer: SFSpeechRecognizer?
    private var recognitionRequest: SFSpeechAudioBufferRecognitionRequest?
    private var recognitionTask: SFSpeechRecognitionTask?
    private var lastTranscription: SFTranscription?
    private var acceptedText = ""
    private var pendingText = ""
    private var activeGeneration = 0
    private var stopRequestedGeneration = 0
    private var finalizationDeadline: DispatchWorkItem?

    private init() {
        if SFSpeechRecognizer.authorizationStatus() == .notDetermined {
            SFSpeechRecognizer.requestAuthorization { status in
                if status != .authorized {
                    print(
                        "Speech recognition authorization unavailable: "
                            + "\(status.rawValue)"
                    )
                }
            }
        }
    }

    @discardableResult
    func startRecognition(identifier: String, generation: Int) -> Bool {
        guard generation > 0 else { return false }
        cancelWithoutEmission()

        guard SFSpeechRecognizer.authorizationStatus() == .authorized else {
            return false
        }
        let localeIdentifier = Self.locales[identifier] ?? "en-US"
        guard let recognizer = SFSpeechRecognizer(
            locale: Locale(identifier: localeIdentifier)
        ), recognizer.isAvailable, recognizer.supportsOnDeviceRecognition else {
            return false
        }

        do {
            let audioSession = AVAudioSession.sharedInstance()
            try audioSession.setCategory(.playback, options: .mixWithOthers)
            try audioSession.setActive(true)
        } catch {
            print("Speech audio-session setup failed: \(type(of: error))")
            return false
        }

        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true
        request.requiresOnDeviceRecognition = true

        activeGeneration = generation
        stopRequestedGeneration = 0
        acceptedText = ""
        pendingText = ""
        lastTranscription = nil
        self.recognizer = recognizer
        recognitionRequest = request

        let recognitionGeneration = generation
        recognitionTask = recognizer.recognitionTask(with: request) {
            [weak self] result, error in
            guard
                let self,
                self.activeGeneration == recognitionGeneration
            else {
                return
            }
            if let error {
                if self.stopRequestedGeneration == recognitionGeneration {
                    self.finishRecognition(
                        generation: recognitionGeneration,
                        finality: "framework_error_partial"
                    )
                } else {
                    print("Speech recognition failed: \(type(of: error))")
                }
                return
            }
            guard let result else { return }
            let transcription = result.bestTranscription
            if let previous = self.lastTranscription,
               (transcription.segments.count < previous.segments.count ||
                transcription.segments.count == 1) {
                self.acceptedText += self.pendingText
                self.pendingText = ""
            }
            self.pendingText = transcription.formattedString
            self.lastTranscription = transcription

            if result.isFinal,
               self.stopRequestedGeneration == recognitionGeneration {
                self.finishRecognition(
                    generation: recognitionGeneration,
                    finality: "framework_final"
                )
            }
        }
        return true
    }

    @discardableResult
    func stopRecognition(generation: Int) -> Bool {
        guard generation > 0, generation == activeGeneration else {
            return false
        }
        if stopRequestedGeneration == generation {
            return true
        }

        stopRequestedGeneration = generation
        recognitionRequest?.endAudio()
        finalizationDeadline?.cancel()

        let deadline = DispatchWorkItem { [weak self] in
            guard
                let self,
                self.activeGeneration == generation,
                self.stopRequestedGeneration == generation
            else {
                return
            }
            self.finishRecognition(
                generation: generation,
                finality: "timeout_partial"
            )
        }
        finalizationDeadline = deadline
        DispatchQueue.main.asyncAfter(
            deadline: .now() + 2.5,
            execute: deadline
        )
        return true
    }

    func appendPCMData(_ pcmData: Data) {
        guard
            activeGeneration > 0,
            stopRequestedGeneration == 0,
            let recognitionRequest,
            pcmData.count == 3_200,
            pcmData.count.isMultiple(of: MemoryLayout<Int16>.size),
            let format = AVAudioFormat(
                commonFormat: .pcmFormatInt16,
                sampleRate: 16_000,
                channels: 1,
                interleaved: false
            )
        else {
            return
        }
        let frames = AVAudioFrameCount(
            pcmData.count / MemoryLayout<Int16>.size
        )
        guard
            let buffer = AVAudioPCMBuffer(
                pcmFormat: format,
                frameCapacity: frames
            ),
            let destination = buffer.int16ChannelData?.pointee
        else {
            return
        }
        buffer.frameLength = frames
        pcmData.withUnsafeBytes { source in
            guard let baseAddress = source.baseAddress else { return }
            destination.update(
                from: baseAddress.assumingMemoryBound(to: Int16.self),
                count: Int(frames)
            )
        }
        recognitionRequest.append(buffer)
    }

    private func finishRecognition(generation: Int, finality: String) {
        guard generation == activeGeneration else { return }
        let transcript = (acceptedText + pendingText)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        finalizationDeadline?.cancel()
        finalizationDeadline = nil
        recognitionTask?.cancel()
        recognitionRequest = nil
        recognitionTask = nil
        recognizer = nil
        lastTranscription = nil
        acceptedText = ""
        pendingText = ""
        activeGeneration = 0
        stopRequestedGeneration = 0
        deactivateAudioSession(label: "teardown")

        DispatchQueue.main.async {
            BluetoothManager.shared.blueSpeechSink?([
                "script": transcript,
                "generation": generation,
                "is_final": true,
                "finality": finality,
            ])
        }
    }

    private func cancelWithoutEmission() {
        finalizationDeadline?.cancel()
        finalizationDeadline = nil
        recognitionRequest?.endAudio()
        recognitionTask?.cancel()
        recognitionRequest = nil
        recognitionTask = nil
        recognizer = nil
        lastTranscription = nil
        acceptedText = ""
        pendingText = ""
        activeGeneration = 0
        stopRequestedGeneration = 0
        deactivateAudioSession(label: "cancellation")
    }

    private func deactivateAudioSession(label: String) {
        do {
            try AVAudioSession.sharedInstance().setActive(false)
        } catch {
            print(
                "Speech audio-session \(label) failed: \(type(of: error))"
            )
        }
    }
}
""",
    )
    write(
        "test/runtime/ios_speech_finalization_contract_test.dart",
        r"""
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('iOS speech waits for framework final or explicit bounded fallback', () {
    final source =
        File('ios/Runner/SpeechStreamRecognizer.swift').readAsStringSync();

    expect(source, contains('result.isFinal'));
    expect(source, contains('"framework_final"'));
    expect(source, contains('"timeout_partial"'));
    expect(source, contains('recognitionRequest?.endAudio()'));
    expect(source, contains('"finality": finality'));
  });
}
""",
    )


def update_machine_truth() -> None:
    write(
        "README.md",
        f"""
# Hepta Glasses OS

Hepta Glasses OS is the deterministic mobile edge and control-plane reference
architecture for Even Realities G1-class smart glasses. The repository contains
a Flutter companion, Android/iOS BLE and audio integration, a deterministic
effect runtime, reference control-plane services, qualification tools, and
operational contracts.

The repository does **not** contain vendor-authorized G1 firmware, bootloader,
secure-boot keys, production provider credentials, production signing
identities, or proof of physical-device qualification.

## Canonical truth

The active source-plan revision is `{REVISION}`:

- `docs/PROJECT_STATE.json` — single machine-readable current-state source;
- `docs/HEPTA_GLASSES_CANONICAL_DEVELOPMENT_PLAN.md`;
- `docs/CURRENT_STATE.md`;
- `docs/PLATFORM_CAPABILITY_MATRIX.md`;
- `docs/PROTOCOL_CONTRACT.md`;
- `docs/GAP_LEDGER.yaml`;
- `docs/EVIDENCE_INDEX.yaml`.

Exact commit, tree, workflow-run, artifact, and reviewer identities are generated
outside the commit by CI attestations. They are never hand-written as the
"current SHA" inside the commit they describe.

## Source validation

```bash
python3 tools/validate_repository.py
python3 -m unittest discover -s services -p 'test_*.py'
python3 -m unittest discover -s adapters -p 'test_*.py'
python3 -m compileall -q services adapters tools
flutter pub get
dart format --output=none --set-exit-if-changed lib test
flutter analyze --no-fatal-infos
flutter test
bash tools/run_native_sanitizers.sh build/evidence/source-native-sanitizer.json
```

The only workflow authority retained in the candidate tree is
`.github/workflows/ci.yml`; it is read-only and binds evidence to the exact
unchanged head.

## Claim ceiling

A source pass proves source only. Physical G1 behavior, deployed identity and
attestation, provider/OAuth receipts, credential revocation, vendor firmware
authority, independent assurance, signed binaries, pilot outcomes, rollout,
rollback, store approval, and product release remain blocked until their
required E5-E7 evidence exists.
""",
    )

    write(
        "docs/CURRENT_STATE.md",
        f"""
# Hepta Glasses OS current state

Last updated: 2026-08-31
Canonical plan revision: `{REVISION}`

## Authoritative state model

`docs/PROJECT_STATE.json` is the machine-readable current-state source. This
file is a human explanation of that model. Exact commit SHA, tree SHA, GitHub
Actions run, artifact digest, and review identity are external attestations and
are not self-referential prose fields.

## Repository-side G8 closure

The G8 source candidate converges both G7 histories and retains the stricter
runtime tree while removing temporary write-capable remediation workflows. It
contains:

- one exact-key BLE response owner instead of competing ordinary/next slots;
- Android notification-plus-MTU readiness and a bounded serialized write queue;
- iOS speech finalization that waits for `result.isFinal` or emits an explicit
  bounded partial-fallback finality;
- deterministic runtime policy, leases, journal-before-effect execution,
  idempotency, recovery, cancellation, and bounded physical-effect scheduling;
- provider-neutral mobile model access, reference identity/realtime/capability
  services, Skill/Memory controls, source SBOM/provenance/history gates, and
  native sanitizer coverage;
- one read-only CI workflow and machine-generated exact-head evidence.

These are source claims only until the exact candidate head passes all required
CI lanes.

## Platform truth

Android and iOS both contain G1 BLE/display/audio transport source. Android
speech-to-text remains unavailable in the product path until a production PCM
ASR adapter is supplied. iOS supports on-device speech where the OS reports it
available, with framework-final versus bounded fallback truth exposed
explicitly.

## External gates

Physical G1 qualification; deployed KMS/HSM and platform attestation; provider
credential revocation; complete canonical `main` protection; vendor firmware,
bootloader, secure boot and OTA authority; production provider/OAuth receipts;
independent security/privacy/legal/accessibility/safety review; release signing,
pilot telemetry, kill switch, rollback, and store approval remain external
evidence gates. Source code cannot truthfully manufacture those records.
""",
    )

    project_state = {
        "schema_version": 1,
        "plan_revision": REVISION,
        "product_stage": "pre_alpha_source_candidate",
        "canonical_source_branch": "codex/hepta-glasses-gap-closure-g8",
        "source_truth": {
            "single_ci_authority": ".github/workflows/ci.yml",
            "exact_head_attestation_location": (
                "GitHub Actions artifact and PR checks"
            ),
            "self_referential_sha_forbidden": True,
            "source_gate_required": True,
        },
        "platforms": {
            "android": {
                "ble_transport": "source_implemented",
                "bounded_write_queue": "source_implemented",
                "mtu_readiness": "source_implemented",
                "speech_to_text": "unsupported_until_provider_adapter",
                "physical_qualification": "blocked_external",
            },
            "ios": {
                "ble_transport": "source_implemented",
                "bounded_write_queue": "source_implemented",
                "speech_to_text": "source_implemented_conditional",
                "speech_finality": (
                    "framework_final_or_explicit_bounded_fallback"
                ),
                "physical_qualification": "blocked_external",
            },
        },
        "external_gates": [
            "physical_g1_qualification",
            "production_identity_attestation_and_revocation",
            "provider_credential_incident_closure",
            "canonical_main_protection_verification",
            "vendor_firmware_and_ota_authority",
            "production_realtime_oauth_and_receipts",
            "independent_assurance",
            "release_signing_pilot_rollout_and_store_approval",
        ],
    }
    write(
        "docs/PROJECT_STATE.json",
        json.dumps(project_state, ensure_ascii=False, indent=2),
    )

    write(
        "docs/PLATFORM_CAPABILITY_MATRIX.md",
        """
# Platform capability matrix

| Capability | Android | iOS | Current evidence |
|---|---|---|---|
| BLE discovery and pair selection | Source implemented | Source implemented | CI + physical pending |
| Independent left/right readiness | Descriptor + MTU gated | Notification gated | Physical pending |
| Bounded native write flow | Serialized queue, capacity 128 | Serialized queue, capacity 128 | CI + physical pending |
| LC3 decode | Source implemented | Source implemented | Sanitizer + physical pending |
| Speech-to-text | Unsupported until production PCM ASR adapter | Conditional on on-device Speech availability | Physical/language matrix pending |
| Speech finality | Not available | Framework final or explicit bounded fallback | Physical pending |
| Text/display paging | Source implemented | Source implemented | Physical pending |
| BMP transfer | Source implemented with terminal ACK/CRC checks | Same Dart state machine | Physical pending |
| Notifications | Source implemented | Source implemented | Physical/privacy pending |
| Background/reconnect behavior | Not qualified | Not qualified | Open physical matrix |
| Production identity/attestation | Contract only | Contract only | External deployment required |

No cell marked “source implemented” is a physical-device or production claim.
""",
    )

    write(
        "docs/PROTOCOL_CONTRACT.md",
        """
# G1 transport and response-correlation contract

## Identity and readiness

A product connection is a generation-bound pair of independently identified
left and right peripherals. A leg is not ready merely because GATT connected.
Android requires service discovery, required characteristics, notification
descriptor success, an ATT MTU of at least 203 bytes, and acceptance of the
initialization write. Pair-level ready requires both legs.

## Write ownership

Every request has exactly one owner identified by:

```text
(connection generation, side, command)
```

The implementation permits only one in-flight owner for that key. A response
cannot complete two waiters. Timeout after native write is indeterminate and
quarantines the key until a late response is observed or the connection
generation changes.

## Response shape

A response must have a non-empty frame, a known side, the current generation,
the expected command, and command-specific minimum length/status fields.
Unsolicited `0xF5` device events are routed separately and never satisfy a
request waiter.

## Dual-leg effects

Pair-level success requires explicit success from both legs. Left success plus
right failure is degraded/indeterminate external state, not a silent failure.
Blind replay after a native write may have occurred is forbidden.

## Bulk transfer

BMP packets are bounded to 256 packets and 194 payload bytes per packet.
Native write refusal aborts. Completion requires a valid `0x20` terminal ACK
and a valid `0x16` CRC response. Physical qualification must test loss,
reordering, disconnect, reconnect, late ACK, and one-leg completion.

## Versioning

Firmware command semantics remain vendor-owned. A new firmware behavior or
frame shape requires a compatibility record, digital-twin fixture, negative
tests, and physical traces before the product capability matrix is promoted.
""",
    )

    write(
        "docs/operations/SOURCE_ATTESTATION_RUNBOOK.md",
        """
# Source attestation runbook

Exact source identity must be generated outside the commit being attested.

## Required subject

An attestation names the repository, exact commit SHA, exact tree SHA, base
commit, workflow file SHA, workflow run ID, plan revision, and artifact digest.

## Required checks

`repository-contracts`, `flutter`, `android-native`, `ios-native`,
`native-sanitizers`, `secret-and-boundary-scan`, and `source-evidence` must be
non-empty and successful on the same unchanged head.

## Review binding

Any push invalidates prior approval. An eligible reviewer other than the last
pusher approves only after the full matrix succeeds and all conversations are
resolved.

## Forbidden patterns

- hand-writing “current exact SHA” inside the commit it describes;
- treating a parent or source-export run as exact-head evidence;
- accepting skipped or empty jobs;
- promoting E0-E4 evidence to physical, deployed, independent-review, or
  release evidence;
- retaining a write-capable remediation workflow in the candidate tree.
""",
    )

    write(
        "docs/development/G8_SOURCE_CLOSURE.md",
        f"""
# G8 source closure package

Revision: `{REVISION}`

G8 converges the two divergent G7 histories while explicitly choosing the
stricter source tree and rejecting stale generated workflow authority.

## Closed repository blockers

- competing G7 histories are joined by one merge ancestry;
- every temporary write-capable workflow is removed from the candidate tree;
- BLE ordinary and next-response waiters share one exact request slot;
- Android writes are bounded and serialized, and readiness waits for
  notification plus MTU contract completion;
- iOS waits for framework-final speech or emits an explicit bounded fallback;
- product package identifiers and visible iOS naming are normalized;
- current state is machine-readable and exact-head identity is externalized;
- platform and protocol capability contracts are explicit and testable.

## Source exit

The package is E4 only when the complete read-only CI matrix succeeds on one
unchanged head and the content-addressed source evidence verifies that head.

## Product non-closure

G8 does not manufacture physical device, production infrastructure, vendor,
independent review, signing, pilot, rollout, rollback, or store evidence.
""",
    )

    write(
        "docs/README.md",
        """
# Hepta Glasses documentation index

## Canonical current truth

1. `PROJECT_STATE.json` — single machine-readable current-state source.
2. `HEPTA_GLASSES_CANONICAL_DEVELOPMENT_PLAN.md` — normative gates and invariants.
3. `CURRENT_STATE.md` — human explanation of demonstrated and blocked state.
4. `PLATFORM_CAPABILITY_MATRIX.md` — Android/iOS capability truth.
5. `PROTOCOL_CONTRACT.md` — BLE readiness, correlation and failure semantics.
6. `PRODUCT_BOUNDARY.md`, `ARCHITECTURE.md`, `CAPABILITY_MODEL.md`.
7. `THREAT_MODEL.md`, `PRIVACY_MODEL.md`.
8. `GAP_LEDGER.yaml` and `EVIDENCE_INDEX.yaml` — compatibility JSON documents.
9. `operations/SOURCE_ATTESTATION_RUNBOOK.md`.

## Current development package

- `development/G8_SOURCE_CLOSURE.md`

Earlier G3-G7 closure records are historical evidence and do not define current
state.

## Operations

- `operations/PRODUCTION_CONTROL_PLANE_RUNBOOK.md`
- `operations/REALTIME_AND_CAPABILITY_RUNBOOK.md`
- `operations/DEVICE_QUALIFICATION_RUNBOOK.md`
- `operations/REPOSITORY_GOVERNANCE_RUNBOOK.md`
- `operations/PRIVACY_SECURITY_REVIEW_CHECKLIST.md`
- `operations/RELEASE_AND_ROLLBACK_RUNBOOK.md`
- `operations/CREDENTIAL_INCIDENT_RUNBOOK.md`
- `operations/SOURCE_ATTESTATION_RUNBOOK.md`

A normative change updates Project State, Current State, Gap Ledger, Evidence
Index, affected contracts, tests, and the canonical plan in the same commit.
""",
    )

    plan_path = "docs/HEPTA_GLASSES_CANONICAL_DEVELOPMENT_PLAN.md"
    plan = read(plan_path)
    plan = plan.replace(
        "Revision: `2026-08-31-g7`",
        f"Revision: `{REVISION}`",
        1,
    )
    plan = plan.replace(
        "Supersedes: `2026-08-31-g5`, `2026-08-30-g4`, `2026-08-30-g3`, `2026-08-30-g2`, and `2026-08-30-g1`",
        "Supersedes: `2026-08-31-g7`, `2026-08-31-g5`, `2026-08-30-g4`, `2026-08-30-g3`, `2026-08-30-g2`, and `2026-08-30-g1`",
        1,
    )
    plan = plan.replace(
        "## 5. Revision g7 source-convergence order",
        "## 5. Historical G7 source-convergence order",
        1,
    )
    plan += """

## 6. Revision g8 closure order

1. Join both G7 histories without force-replacing reviewed history, while
   resolving the tree to the stricter source implementation.
2. Retain one read-only CI workflow; candidate commits contain no remediation,
   materialization, export, or self-push workflow.
3. Use one BLE request owner per generation/side/command, a bounded Android
   write queue, MTU-gated Android readiness, and explicit iOS speech finality.
4. Generate exact-head identity externally; commits do not claim their own
   future SHA.
5. Keep Android speech unsupported until its production PCM ASR adapter and
   physical qualification exist.
6. Promote source only after the unchanged-head matrix and independent review.
7. Preserve all E5-E7 external gates until real, content-addressed evidence
   exists.
"""
    write(plan_path, plan)

    ledger_path = ROOT / "docs/GAP_LEDGER.yaml"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["schema_version"] = max(int(ledger.get("schema_version", 0)), 5)
    ledger["plan_revision"] = REVISION
    new_gaps = [
        {
            "id": "HG-0052",
            "title": (
                "Divergent G7 branches and competing write-capable workflows "
                "obscured repository authority"
            ),
            "status": "CLOSED_SOURCE",
            "owner": "repository",
            "evidence": [
                ".github/workflows/ci.yml",
                "docs/development/G8_SOURCE_CLOSURE.md",
                "docs/PROJECT_STATE.json",
            ],
        },
        {
            "id": "HG-0053",
            "title": (
                "Ordinary and next BLE waiters could share one timeout key "
                "and leave a request permanently pending"
            ),
            "status": "CLOSED_SOURCE",
            "owner": "device-hal",
            "evidence": [
                "lib/ble_manager.dart",
                "test/runtime/ble_request_slot_regression_test.dart",
                "docs/PROTOCOL_CONTRACT.md",
            ],
        },
        {
            "id": "HG-0054",
            "title": (
                "Android declared readiness before MTU completion and lacked "
                "a bounded serialized native write queue"
            ),
            "status": "CLOSED_SOURCE",
            "owner": "android-device-hal",
            "evidence": [
                "android/app/src/main/kotlin/com/example/demo_ai_even/bluetooth/BleManager.kt",
                "android/app/src/main/kotlin/com/example/demo_ai_even/model/BleDevice.kt",
                "android/app/src/main/kotlin/org/trillionnium/heptaglasses/bluetooth/BoundedWriteQueue.kt",
                "android/app/src/test/kotlin/org/trillionnium/heptaglasses/bluetooth/BoundedWriteQueueTest.kt",
            ],
        },
        {
            "id": "HG-0055",
            "title": (
                "iOS cancelled recognition immediately and labeled the latest "
                "partial transcript as framework-final"
            ),
            "status": "CLOSED_SOURCE",
            "owner": "ios-assistant",
            "evidence": [
                "ios/Runner/SpeechStreamRecognizer.swift",
                "test/runtime/ios_speech_finalization_contract_test.dart",
                "docs/PLATFORM_CAPABILITY_MATRIX.md",
            ],
        },
        {
            "id": "HG-0056",
            "title": (
                "Current-state prose embedded stale self-referential SHA "
                "claims and lacked one machine truth source"
            ),
            "status": "CLOSED_SOURCE",
            "owner": "repository",
            "evidence": [
                "docs/PROJECT_STATE.json",
                "docs/CURRENT_STATE.md",
                "docs/operations/SOURCE_ATTESTATION_RUNBOOK.md",
                "tools/validate_repository.py",
            ],
        },
    ]
    existing_ids = {gap.get("id") for gap in ledger.get("gaps", [])}
    duplicates = [gap["id"] for gap in new_gaps if gap["id"] in existing_ids]
    if duplicates:
        fail(f"Gap Ledger already contains G8 IDs: {duplicates}")
    ledger["gaps"].extend(new_gaps)
    ledger_path.write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    index_path = ROOT / "docs/EVIDENCE_INDEX.yaml"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["schema_version"] = max(int(index.get("schema_version", 0)), 5)
    index["plan_revision"] = REVISION
    index.setdefault("source_records", []).append(
        {
            "id": "EV-SRC-G8-CANDIDATE-V1",
            "path": "docs/development/G8_SOURCE_CLOSURE.md",
            "levels": ["E0", "E1", "E2", "E3"],
            "claim": (
                "Converged G8 source candidate; E4 exists only after the "
                "unchanged exact-head CI artifact and independent review"
            ),
        }
    )
    index_path.write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    release_contract_path = ROOT / "contracts/release-gates-v1.json"
    release_contract = json.loads(
        release_contract_path.read_text(encoding="utf-8")
    )
    release_contract["contracts_version"] = REVISION
    release_contract_path.write_text(
        json.dumps(release_contract, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    template_path = ROOT / "evidence/templates/product-release-bundle.template.json"
    template = json.loads(template_path.read_text(encoding="utf-8"))
    if not isinstance(template.get("source"), dict):
        fail("product release template has no source object")
    template["source"]["contracts_version"] = REVISION
    template_path.write_text(
        json.dumps(template, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    for revision_path in (
        "services/qualification/release_gate.py",
        "services/qualification/test_release_gate.py",
    ):
        revision_text = read(revision_path)
        if "2026-08-31-g7" not in revision_text:
            fail(f"{revision_path}: expected G7 release revision")
        write(
            revision_path,
            revision_text.replace("2026-08-31-g7", REVISION),
        )

    validator_path = "tools/validate_repository.py"
    validator = read(validator_path)
    validator = validator.replace(
        'CANONICAL_REVISION = "2026-08-31-g7"',
        f'CANONICAL_REVISION = "{REVISION}"',
        1,
    )
    validator = validator.replace(
        '    "docs/README.md",\n',
        '    "docs/README.md",\n'
        '    "docs/PROJECT_STATE.json",\n'
        '    "docs/PLATFORM_CAPABILITY_MATRIX.md",\n'
        '    "docs/PROTOCOL_CONTRACT.md",\n',
        1,
    )
    validator = validator.replace(
        '    "docs/development/G7_SOURCE_CONVERGENCE.md",\n',
        '    "docs/development/G7_SOURCE_CONVERGENCE.md",\n'
        '    "docs/development/G8_SOURCE_CLOSURE.md",\n',
        1,
    )
    validator = validator.replace(
        '    "docs/operations/CREDENTIAL_INCIDENT_RUNBOOK.md",\n',
        '    "docs/operations/CREDENTIAL_INCIDENT_RUNBOOK.md",\n'
        '    "docs/operations/SOURCE_ATTESTATION_RUNBOOK.md",\n',
        1,
    )
    validator = validator.replace(
        'if not isinstance(gaps, list) or len(gaps) < 51:',
        'if not isinstance(gaps, list) or len(gaps) < 56:',
        1,
    )
    insertion_point = "\ndef validate_boundaries() -> None:\n"
    state_check = r'''


def validate_project_state() -> None:
    state = read_json(ROOT / "docs/PROJECT_STATE.json")
    if state.get("plan_revision") != CANONICAL_REVISION:
        fail("Project State is not bound to the canonical revision")
    if state.get("product_stage") != "pre_alpha_source_candidate":
        fail("Project State overstates the product stage")
    source_truth = state.get("source_truth")
    if not isinstance(source_truth, dict):
        fail("Project State lacks source truth")
    if source_truth.get("single_ci_authority") != ".github/workflows/ci.yml":
        fail("Project State names a competing CI authority")
    if source_truth.get("self_referential_sha_forbidden") is not True:
        fail("Project State permits self-referential SHA claims")

    ble = (ROOT / "lib/ble_manager.dart").read_text(encoding="utf-8")
    if "_nextReceive" in ble or "_nextReceiveKey" in ble:
        fail("legacy dual BLE response slots remain")
    speech = (ROOT / "ios/Runner/SpeechStreamRecognizer.swift").read_text(
        encoding="utf-8"
    )
    for fragment in ("result.isFinal", '"framework_final"', '"timeout_partial"'):
        if fragment not in speech:
            fail(f"iOS speech finalization contract lacks {fragment}")

'''
    if insertion_point not in validator:
        fail("validator insertion point missing")
    validator = validator.replace(
        insertion_point, state_check + insertion_point, 1
    )
    validator = validator.replace(
        "        validate_gap_ledger,\n",
        "        validate_gap_ledger,\n        validate_project_state,\n",
        1,
    )
    write(validator_path, validator)


def clean_candidate_authority() -> None:
    workflows = ROOT / ".github/workflows"
    for path in workflows.glob("*.yml"):
        if path.name not in {"ci.yml", BOOTSTRAP_WORKFLOW.name}:
            path.unlink()

    if BOOTSTRAP_WORKFLOW.exists():
        BOOTSTRAP_WORKFLOW.unlink()
    Path(__file__).unlink()


def main() -> int:
    rename_product_identity()
    unify_ble_request_slot()
    harden_android_transport()
    harden_ios_speech_finalization()
    update_machine_truth()
    clean_candidate_authority()
    print("G8 source convergence materialized")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
