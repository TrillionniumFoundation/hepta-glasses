package com.example.demo_ai_even.bluetooth

import com.example.demo_ai_even.MainActivity
import com.example.demo_ai_even.model.BlePairDevice
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
            "startEvenAI" -> result.error(
                "SpeechRecognitionUnavailable",
                "Android PCM speech adapter is not configured",
                null,
            )
            "stopEvenAI" -> result.success(true)
            "getApplicationSupportPath" ->
                result.success(context.filesDir.absolutePath)
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

    fun flutterFoundPairedGlasses(device: BlePairDevice) =
        methodChannel.invokeMethod("foundPairedGlasses", device.toInfoJson())

    fun flutterGlassesConnected(deviceInfo: Map<String, Any>) =
        methodChannel.invokeMethod("glassesConnected", deviceInfo)

    fun flutterGlassesConnecting(deviceInfo: Map<String, Any>) =
        methodChannel.invokeMethod("glassesConnecting", deviceInfo)

    fun flutterGlassesDisconnected(deviceInfo: Map<String, Any>) =
        methodChannel.invokeMethod("glassesDisconnected", deviceInfo)
}
