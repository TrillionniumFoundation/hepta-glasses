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

    private let stateLock = NSLock()
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

        stateLock.lock()
        activeGeneration = generation
        stopRequestedGeneration = 0
        acceptedText = ""
        pendingText = ""
        lastTranscription = nil
        self.recognizer = recognizer
        recognitionRequest = request
        stateLock.unlock()

        let recognitionGeneration = generation
        let task = recognizer.recognitionTask(with: request) { [weak self] result, error in
            guard let self else { return }

            if let error {
                self.stateLock.lock()
                let shouldFinish =
                    self.activeGeneration == recognitionGeneration &&
                    self.stopRequestedGeneration == recognitionGeneration
                self.stateLock.unlock()
                if shouldFinish {
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

            self.stateLock.lock()
            guard self.activeGeneration == recognitionGeneration else {
                self.stateLock.unlock()
                return
            }
            let transcription = result.bestTranscription
            if let previous = self.lastTranscription,
               (transcription.segments.count < previous.segments.count ||
                transcription.segments.count == 1) {
                self.acceptedText += self.pendingText
                self.pendingText = ""
            }
            self.pendingText = transcription.formattedString
            self.lastTranscription = transcription
            let shouldFinish =
                result.isFinal &&
                self.stopRequestedGeneration == recognitionGeneration
            self.stateLock.unlock()

            if shouldFinish {
                self.finishRecognition(
                    generation: recognitionGeneration,
                    finality: "framework_final"
                )
            }
        }

        stateLock.lock()
        if activeGeneration == generation {
            recognitionTask = task
            stateLock.unlock()
            return true
        }
        stateLock.unlock()
        task.cancel()
        return false
    }

    @discardableResult
    func stopRecognition(generation: Int) -> Bool {
        stateLock.lock()
        guard generation > 0, generation == activeGeneration else {
            stateLock.unlock()
            return false
        }
        if stopRequestedGeneration == generation {
            stateLock.unlock()
            return true
        }

        stopRequestedGeneration = generation
        let request = recognitionRequest
        finalizationDeadline?.cancel()
        let deadline = DispatchWorkItem { [weak self] in
            self?.finishRecognition(
                generation: generation,
                finality: "timeout_partial"
            )
        }
        finalizationDeadline = deadline
        stateLock.unlock()

        request?.endAudio()
        DispatchQueue.main.asyncAfter(
            deadline: .now() + 2.5,
            execute: deadline
        )
        return true
    }

    func appendPCMData(_ pcmData: Data) {
        guard
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

        stateLock.lock()
        guard
            activeGeneration > 0,
            stopRequestedGeneration == 0,
            let request = recognitionRequest
        else {
            stateLock.unlock()
            return
        }
        request.append(buffer)
        stateLock.unlock()
    }

    private func finishRecognition(generation: Int, finality: String) {
        stateLock.lock()
        guard generation == activeGeneration else {
            stateLock.unlock()
            return
        }
        let transcript = (acceptedText + pendingText)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let task = recognitionTask
        finalizationDeadline?.cancel()
        finalizationDeadline = nil
        recognitionRequest = nil
        recognitionTask = nil
        recognizer = nil
        lastTranscription = nil
        acceptedText = ""
        pendingText = ""
        activeGeneration = 0
        stopRequestedGeneration = 0
        stateLock.unlock()

        task?.cancel()
        deactivateAudioSession(label: "teardown")
        let frameworkFinal = finality == "framework_final"
        let emittedTranscript = frameworkFinal ? transcript : ""
        DispatchQueue.main.async {
            BluetoothManager.shared.blueSpeechSink?([
                "script": emittedTranscript,
                "generation": generation,
                "is_final": true,
                "is_framework_final": frameworkFinal,
                "partial_discarded": !frameworkFinal,
                "partial_character_count": frameworkFinal ? 0 : transcript.count,
                "finality": finality,
            ])
        }
    }

    private func cancelWithoutEmission() {
        stateLock.lock()
        let request = recognitionRequest
        let task = recognitionTask
        finalizationDeadline?.cancel()
        finalizationDeadline = nil
        recognitionRequest = nil
        recognitionTask = nil
        recognizer = nil
        lastTranscription = nil
        acceptedText = ""
        pendingText = ""
        activeGeneration = 0
        stopRequestedGeneration = 0
        stateLock.unlock()

        request?.endAudio()
        task?.cancel()
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
