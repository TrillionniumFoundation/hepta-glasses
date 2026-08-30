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

    private init() {
        if SFSpeechRecognizer.authorizationStatus() == .notDetermined {
            SFSpeechRecognizer.requestAuthorization { status in
                if status != .authorized {
                    print("Speech recognition authorization unavailable: \(status.rawValue)")
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
        acceptedText = ""
        pendingText = ""
        lastTranscription = nil
        self.recognizer = recognizer
        recognitionRequest = request

        let recognitionGeneration = generation
        recognitionTask = recognizer.recognitionTask(with: request) { [weak self] result, error in
            guard
                let self,
                self.activeGeneration == recognitionGeneration
            else {
                return
            }
            if let error {
                print("Speech recognition failed: \(type(of: error))")
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
        }
        return true
    }

    @discardableResult
    func stopRecognition(generation: Int) -> Bool {
        guard generation > 0, generation == activeGeneration else {
            return false
        }
        let transcript = (acceptedText + pendingText)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let stoppedGeneration = activeGeneration
        recognitionRequest?.endAudio()
        recognitionTask?.cancel()
        recognitionRequest = nil
        recognitionTask = nil
        recognizer = nil
        lastTranscription = nil
        acceptedText = ""
        pendingText = ""
        activeGeneration = 0
        do {
            try AVAudioSession.sharedInstance().setActive(false)
        } catch {
            print("Speech audio-session teardown failed: \(type(of: error))")
        }
        DispatchQueue.main.async {
            BluetoothManager.shared.blueSpeechSink?([
                "script": transcript,
                "generation": stoppedGeneration,
                "is_final": true,
            ])
        }
        return true
    }

    func appendPCMData(_ pcmData: Data) {
        guard
            activeGeneration > 0,
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

    private func cancelWithoutEmission() {
        recognitionRequest?.endAudio()
        recognitionTask?.cancel()
        recognitionRequest = nil
        recognitionTask = nil
        recognizer = nil
        lastTranscription = nil
        acceptedText = ""
        pendingText = ""
        activeGeneration = 0
        do {
            try AVAudioSession.sharedInstance().setActive(false)
        } catch {
            print("Speech audio-session cancellation failed: \(type(of: error))")
        }
    }
}
