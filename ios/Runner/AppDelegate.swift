import Flutter
import UIKit

@main
@objc class AppDelegate: FlutterAppDelegate {
    private let blueInstance = BluetoothManager.shared

    override func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
    ) -> Bool {
        GeneratedPluginRegistrant.register(with: self)
        guard let controller = window?.rootViewController as? FlutterViewController else {
            return false
        }
        let messenger = controller.binaryMessenger
        let channel = FlutterMethodChannel(
            name: "method.bluetooth",
            binaryMessenger: messenger
        )
        blueInstance.attach(channel: channel)

        channel.setMethodCallHandler { [weak self] call, result in
            guard let self else {
                result(
                    FlutterError(
                        code: "RuntimeUnavailable",
                        message: "Native runtime is unavailable",
                        details: nil
                    )
                )
                return
            }
            switch call.method {
            case "startScan":
                self.blueInstance.startScan(result: result)
            case "stopScan":
                self.blueInstance.stopScan(result: result)
            case "connectToGlasses":
                guard
                    let arguments = call.arguments as? [String: Any],
                    let deviceName = arguments["deviceName"] as? String,
                    !deviceName.isEmpty
                else {
                    result(
                        FlutterError(
                            code: "InvalidArguments",
                            message: "deviceName is required",
                            details: nil
                        )
                    )
                    return
                }
                self.blueInstance.connectToDevice(
                    deviceName: deviceName,
                    result: result
                )
            case "disconnectFromGlasses":
                self.blueInstance.disconnectFromGlasses(result: result)
            case "send":
                guard let parameters = call.arguments as? [String: Any] else {
                    result(
                        FlutterError(
                            code: "InvalidArguments",
                            message: "send arguments are required",
                            details: nil
                        )
                    )
                    return
                }
                result(self.blueInstance.sendData(params: parameters))
            case "startEvenAI":
                guard
                    let arguments = call.arguments as? [String: Any],
                    let generation = arguments["generation"] as? Int,
                    generation > 0
                else {
                    result(
                        FlutterError(
                            code: "InvalidArguments",
                            message: "assistant generation is required",
                            details: nil
                        )
                    )
                    return
                }
                self.blueInstance.beginAudioSession()
                guard SpeechStreamRecognizer.shared.startRecognition(
                    identifier: "EN",
                    generation: generation
                ) else {
                    result(
                        FlutterError(
                            code: "SpeechRecognitionUnavailable",
                            message: "On-device speech recognition is unavailable",
                            details: nil
                        )
                    )
                    return
                }
                result(true)
            case "stopEvenAI":
                guard
                    let arguments = call.arguments as? [String: Any],
                    let generation = arguments["generation"] as? Int,
                    generation > 0
                else {
                    result(
                        FlutterError(
                            code: "InvalidArguments",
                            message: "assistant generation is required",
                            details: nil
                        )
                    )
                    return
                }
                result(
                    SpeechStreamRecognizer.shared.stopRecognition(
                        generation: generation
                    )
                )
            case "getApplicationSupportPath":
                do {
                    let root = try FileManager.default.url(
                        for: .applicationSupportDirectory,
                        in: .userDomainMask,
                        appropriateFor: nil,
                        create: true
                    )
                    result(root.path)
                } catch {
                    result(
                        FlutterError(
                            code: "ApplicationSupportUnavailable",
                            message: error.localizedDescription,
                            details: nil
                        )
                    )
                }
            default:
                result(FlutterMethodNotImplemented)
            }
        }

        FlutterEventChannel(
            name: "eventBleReceive",
            binaryMessenger: messenger
        ).setStreamHandler(self)
        FlutterEventChannel(
            name: "eventSpeechRecognize",
            binaryMessenger: messenger
        ).setStreamHandler(self)

        return super.application(
            application,
            didFinishLaunchingWithOptions: launchOptions
        )
    }
}

extension AppDelegate: FlutterStreamHandler {
    func onListen(
        withArguments arguments: Any?,
        eventSink events: @escaping FlutterEventSink
    ) -> FlutterError? {
        switch arguments as? String {
        case "eventBleReceive":
            blueInstance.blueInfoSink = events
        case "eventSpeechRecognize":
            blueInstance.blueSpeechSink = events
        default:
            return FlutterError(
                code: "UnknownEventChannel",
                message: "Unsupported event channel",
                details: nil
            )
        }
        return nil
    }

    func onCancel(withArguments arguments: Any?) -> FlutterError? {
        switch arguments as? String {
        case "eventBleReceive":
            blueInstance.blueInfoSink = nil
        case "eventSpeechRecognize":
            blueInstance.blueSpeechSink = nil
        default:
            break
        }
        return nil
    }
}
