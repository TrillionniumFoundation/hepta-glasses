package com.example.demo_ai_even.bluetooth

import com.example.demo_ai_even.MainActivity
import com.example.demo_ai_even.model.BlePairDevice
import com.example.demo_ai_even.security.AuditCheckpointSigner
import com.example.demo_ai_even.speech.SpeechTicket
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.EventChannel
import io.flutter.plugin.common.EventChannel.EventSink
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel

object BleChannelHelper {
    private const val METHOD_CHANNEL_BLE_TAG = "method.bluetooth"
    private const val EVENT_BLE_STATUS = "eventBleStatus"
    private const val EVENT_BLE_RECEIVE = "eventBleReceive"
    private const val EVENT_BLE_SPEECH_RECOGNIZE = "eventSpeechRecognize"

    private val eventSinks: MutableMap<String, EventSink> = mutableMapOf()
    private lateinit var bleMethodChannel: BleMethodChannel

    val bleMC: BleMethodChannel
        get() = bleMethodChannel

    fun initChannel(context: MainActivity, flutterEngine: FlutterEngine) {
        val binaryMessenger = flutterEngine.dartExecutor.binaryMessenger
        bleMethodChannel = BleMethodChannel(
            context,
            MethodChannel(binaryMessenger, METHOD_CHANNEL_BLE_TAG),
        )
        EventChannel(binaryMessenger, EVENT_BLE_STATUS).setStreamHandler(context)
        EventChannel(binaryMessenger, EVENT_BLE_RECEIVE).setStreamHandler(context)
        EventChannel(binaryMessenger, EVENT_BLE_SPEECH_RECOGNIZE)
            .setStreamHandler(context)
    }

    fun addEventSink(eventTag: String?, eventSink: EventSink?) {
        if (eventTag == null || eventSink == null) return
        eventSinks[eventTag] = eventSink
    }

    fun removeEventSink(eventTag: String?) {
        eventTag?.let(eventSinks::remove)
    }

    fun bleStatus(data: Any) = eventSinks[EVENT_BLE_STATUS]?.success(data)
    fun bleReceive(data: Any) = eventSinks[EVENT_BLE_RECEIVE]?.success(data)
    fun bleSpeechRecognize(data: Any) =
        eventSinks[EVENT_BLE_SPEECH_RECOGNIZE]?.success(data)
}

class BleMethodChannel(
    private val context: MainActivity,
    private val methodChannel: MethodChannel,
) {
    init {
        methodChannel.setMethodCallHandler(::handle)
    }

    private fun handle(call: MethodCall, result: MethodChannel.Result) {
        when (call.method) {
            "startScan" -> BleManager.instance.startScan(result)
            "stopScan" -> BleManager.instance.stopScan(result)
            "connectToGlasses" -> connectToGlasses(call, result)
            "disconnectFromGlasses" ->
                BleManager.instance.disconnectFromGlasses(result)
            "send" -> send(call, result)
            "startEvenAI" -> startEvenAI(call, result)
            "stopEvenAI" -> stopEvenAI(call, result)
            "getApplicationSupportPath" ->
                result.success(context.filesDir.absolutePath)
            "auditCheckpointMac" -> authenticateAuditCheckpoint(call, result)
            else -> result.notImplemented()
        }
    }

    private fun connectToGlasses(
        call: MethodCall,
        result: MethodChannel.Result,
    ) {
        val deviceChannel =
            (call.arguments as? Map<*, *>)?.get("deviceName") as? String ?: ""
        if (deviceChannel.isEmpty()) {
            result.error("InvalidArguments", "deviceName is required", null)
            return
        }
        BleManager.instance.connectToGlass(
            deviceChannel.replace("Pair_", ""),
            result,
        )
    }

    private fun send(call: MethodCall, result: MethodChannel.Result) {
        val arguments = call.arguments as? Map<*, *>
        if (arguments == null) {
            result.error("InvalidArguments", "send arguments are required", null)
            return
        }
        result.success(BleManager.instance.sendData(arguments))
    }

    private fun startEvenAI(
        call: MethodCall,
        result: MethodChannel.Result,
    ) {
        val arguments = call.arguments as? Map<*, *>
        val sessionId = arguments?.get("sessionId") as? String
        val generation = (arguments?.get("generation") as? Number)?.toInt()
        val connectionGeneration =
            (arguments?.get("connectionGeneration") as? Number)?.toInt()
        val pairIdentity = arguments?.get("pairIdentity") as? String
        val locale = arguments?.get("locale") as? String
        val endpoint = arguments?.get("endpoint") as? String
        val bearerToken = arguments?.get("bearerToken") as? String
        val expiresAt =
            (arguments?.get("expiresAtEpochSeconds") as? Number)?.toLong()
        val maximumAudioBytes =
            (arguments?.get("maximumAudioBytes") as? Number)?.toInt()

        if (sessionId.isNullOrBlank() ||
            generation == null || generation <= 0 ||
            connectionGeneration == null || connectionGeneration <= 0 ||
            pairIdentity.isNullOrBlank() ||
            locale.isNullOrBlank() ||
            endpoint.isNullOrBlank() ||
            bearerToken.isNullOrBlank() ||
            expiresAt == null ||
            maximumAudioBytes == null
        ) {
            result.error(
                "InvalidArguments",
                "A complete speech bootstrap is required",
                null,
            )
            return
        }

        try {
            val accepted = BleManager.instance.startSpeech(
                SpeechTicket(
                    sessionId = sessionId,
                    generation = generation,
                    connectionGeneration = connectionGeneration,
                    pairIdentity = pairIdentity,
                    locale = locale,
                    endpoint = endpoint,
                    bearerToken = bearerToken,
                    expiresAtEpochSeconds = expiresAt,
                    maximumAudioBytes = maximumAudioBytes,
                ),
            )
            if (!accepted) {
                result.error(
                    "SpeechAuthorityStale",
                    "Speech bootstrap does not match the active G1 authority",
                    null,
                )
                return
            }
            result.success(true)
        } catch (_: IllegalArgumentException) {
            result.error(
                "SpeechBootstrapInvalid",
                "Speech bootstrap validation failed",
                null,
            )
        } catch (_: IllegalStateException) {
            result.error(
                "SpeechBootstrapInvalid",
                "Speech bootstrap admission failed",
                null,
            )
        }
    }

    private fun stopEvenAI(
        call: MethodCall,
        result: MethodChannel.Result,
    ) {
        val arguments = call.arguments as? Map<*, *>
        val generation = (arguments?.get("generation") as? Number)?.toInt()
        val connectionGeneration =
            (arguments?.get("connectionGeneration") as? Number)?.toInt()
        val pairIdentity = arguments?.get("pairIdentity") as? String
        val finalize = arguments?.get("finalize") as? Boolean
        if (generation == null || generation <= 0 ||
            connectionGeneration == null || connectionGeneration <= 0 ||
            pairIdentity.isNullOrBlank() ||
            finalize == null
        ) {
            result.error(
                "InvalidArguments",
                "Both generations, pairIdentity and finalize are required",
                null,
            )
            return
        }
        if (!BleManager.instance.stopSpeech(
                generation,
                connectionGeneration,
                pairIdentity,
                finalize,
            )
        ) {
            result.error(
                "SpeechSessionStale",
                "Speech session does not match the active G1 authority",
                null,
            )
            return
        }
        result.success(true)
    }

    private fun authenticateAuditCheckpoint(
        call: MethodCall,
        result: MethodChannel.Result,
    ) {
        val payload =
            (call.arguments as? Map<*, *>)?.get("payload") as? ByteArray
        if (payload == null || payload.isEmpty()) {
            result.error(
                "InvalidArguments",
                "audit checkpoint payload is required",
                null,
            )
            return
        }
        try {
            result.success(AuditCheckpointSigner.authenticate(payload))
        } catch (error: Exception) {
            result.error(
                "AuditCheckpointAuthenticationFailed",
                error::class.java.simpleName,
                null,
            )
        }
    }

    fun flutterFoundPairedGlasses(device: BlePairDevice) =
        methodChannel.invokeMethod("foundPairedGlasses", device.toInfoJson())

    fun flutterGlassesConnected(deviceInfo: Map<String, Any>) =
        methodChannel.invokeMethod("glassesConnected", deviceInfo)

    fun flutterGlassesConnecting(deviceInfo: Map<String, Any>) =
        methodChannel.invokeMethod("glassesConnecting", deviceInfo)

    fun flutterGlassesDisconnected(deviceInfo: Map<String, Any>) =
        methodChannel.invokeMethod("glassesDisconnected", deviceInfo)
}
