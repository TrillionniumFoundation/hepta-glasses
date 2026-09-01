package com.example.demo_ai_even.bluetooth

import android.annotation.SuppressLint
import android.app.Activity
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCallback
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothGattDescriptor
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothProfile
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.Context
import android.os.Build
import android.util.Log
import android.widget.Toast
import com.example.demo_ai_even.cpp.Cpp
import com.example.demo_ai_even.model.BleDevice
import com.example.demo_ai_even.model.BlePairDevice
import io.flutter.plugin.common.MethodChannel
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import java.lang.ref.WeakReference
import java.util.UUID

@SuppressLint("MissingPermission")
class BleManager private constructor() {
    companion object {
        val LOG_TAG: String = BleManager::class.java.simpleName
        private const val SERVICE_UUID =
            "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
        private const val WRITE_CHARACTERISTIC_UUID =
            "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
        private const val READ_CHARACTERISTIC_UUID =
            "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"
        private const val CLIENT_CONFIGURATION_UUID =
            "00002902-0000-1000-8000-00805f9b34fb"
        private const val REQUIRED_MTU = 203
        private const val REQUESTED_MTU = 251
        private const val UNSELECTED_PAIR = "unselected"

        val instance: BleManager by lazy { BleManager() }
    }

    private lateinit var weakActivity: WeakReference<Activity>
    private lateinit var bluetoothManager: BluetoothManager
    private val bluetoothAdapter
        get() = bluetoothManager.adapter
    private val discoveredDevices: MutableList<BleDevice> = mutableListOf()
    private var connectedDevice: BlePairDevice? = null
    private val notificationReadyAddresses: MutableSet<String> = mutableSetOf()
    private val readyAddresses: MutableSet<String> = mutableSetOf()
    private val intentionalDisconnectAddresses: MutableSet<String> = mutableSetOf()

    @Volatile
    private var connectionGeneration = 0

    @Volatile
    private var currentPairIdentity = UNSELECTED_PAIR

    private val decodeScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    private val scanSettings = ScanSettings.Builder()
        .setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY)
        .build()

    private val scanCallback = object : ScanCallback() {
        override fun onScanResult(callbackType: Int, result: ScanResult?) {
            val device = result?.device ?: return
            val name = device.name ?: return
            val parts = name.split("_")
            if (!name.matches(Regex("G\\d+_.*")) ||
                parts.size != 4 ||
                discoveredDevices.any { it.address == device.address }
            ) {
                return
            }
            val channelNumber = parts[1]
            discoveredDevices.add(
                BleDevice.createByDevice(name, device.address, channelNumber),
            )
            val pair = discoveredDevices.filter { it.channelNumber == channelNumber }
            val left = pair.firstOrNull(BleDevice::isLeft) ?: return
            val right = pair.firstOrNull(BleDevice::isRight) ?: return
            BleChannelHelper.bleMC.flutterFoundPairedGlasses(
                BlePairDevice(left, right),
            )
        }

        override fun onScanFailed(errorCode: Int) {
            Log.e(LOG_TAG, "BLE scan failed: $errorCode")
        }
    }

    fun initBluetooth(context: Activity) {
        weakActivity = WeakReference(context)
        bluetoothManager = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            context.getSystemService(BluetoothManager::class.java)
        } else {
            @Suppress("DEPRECATION")
            context.getSystemService(Context.BLUETOOTH_SERVICE) as BluetoothManager
        }
    }

    fun startScan(result: MethodChannel.Result) {
        if (!checkBluetoothStatus()) {
            result.error("Permission", "Bluetooth permission is required", null)
            return
        }
        discoveredDevices.clear()
        bluetoothAdapter.bluetoothLeScanner.startScan(
            null,
            scanSettings,
            scanCallback,
        )
        result.success("Scanning for devices...")
    }

    fun stopScan(result: MethodChannel.Result? = null) {
        if (!checkBluetoothStatus()) {
            result?.error("Permission", "Bluetooth permission is required", null)
            return
        }
        bluetoothAdapter.bluetoothLeScanner.stopScan(scanCallback)
        result?.success("Scan stopped")
    }

    fun connectToGlass(deviceChannel: String, result: MethodChannel.Result) {
        val leftChannel = "_${deviceChannel}_L_"
        val rightChannel = "_${deviceChannel}_R_"
        val left = discoveredDevices.firstOrNull { it.name.contains(leftChannel) }
        val right = discoveredDevices.firstOrNull { it.name.contains(rightChannel) }
        if (left == null || right == null) {
            result.error(
                "PeripheralNotFound",
                "One or both peripherals were not found",
                null,
            )
            return
        }

        disconnectCurrent(notifyFlutter = false)
        connectionGeneration += 1
        currentPairIdentity = "Pair_$deviceChannel"
        intentionalDisconnectAddresses.clear()
        notificationReadyAddresses.clear()
        readyAddresses.clear()
        val pair = BlePairDevice(left, right)
        connectedDevice = pair
        BleChannelHelper.bleMC.flutterGlassesConnecting(
            mapOf(
                "leftDeviceName" to left.name,
                "rightDeviceName" to right.name,
                "generation" to connectionGeneration,
                "pairIdentity" to currentPairIdentity,
            ),
        )

        val activity = weakActivity.get()
        if (activity == null) {
            connectedDevice = null
            currentPairIdentity = UNSELECTED_PAIR
            result.error("ActivityUnavailable", "Activity is unavailable", null)
            return
        }

        val generation = connectionGeneration
        try {
            val leftGatt = bluetoothAdapter.getRemoteDevice(left.address)
                .connectGatt(activity, false, gattCallback(generation))
            left.gatt = leftGatt
            val rightGatt = bluetoothAdapter.getRemoteDevice(right.address)
                .connectGatt(activity, false, gattCallback(generation))
            right.gatt = rightGatt
        } catch (error: Exception) {
            disconnectCurrent(notifyFlutter = true)
            result.error(
                "ConnectionStartFailed",
                error::class.java.simpleName,
                null,
            )
            return
        }
        result.success("Connecting to G1_$deviceChannel ...")
    }

    fun disconnectFromGlasses(result: MethodChannel.Result) {
        disconnectCurrent(notifyFlutter = true)
        result.success("Disconnected all devices.")
    }

    fun sendData(params: Map<*, *>?): Boolean {
        params ?: return false
        val expectedGeneration = (params["expectedGeneration"] as? Number)?.toInt()
        if (expectedGeneration != null && expectedGeneration != connectionGeneration) {
            return false
        }
        val expectedPairIdentity = params["expectedPairIdentity"] as? String
        if (expectedPairIdentity != null && expectedPairIdentity != currentPairIdentity) {
            return false
        }
        if (currentPairIdentity == UNSELECTED_PAIR) return false
        val rawData = params["data"]
        val data = when (rawData) {
            is ByteArray -> rawData
            else -> return false
        }
        if (data.isEmpty()) return false
        return when (params["lr"] as? String) {
            "L" -> sendToSide(data, left = true)
            "R" -> sendToSide(data, left = false)
            null -> sendToSide(data, left = true) &&
                sendToSide(data, left = false)
            else -> false
        }
    }

    private fun checkBluetoothStatus(): Boolean {
        val activity = weakActivity.get() ?: return false
        if (!bluetoothAdapter.isEnabled) {
            Toast.makeText(
                activity,
                "Bluetooth is turned off",
                Toast.LENGTH_SHORT,
            ).show()
            return false
        }
        return BlePermissionUtil.checkBluetoothPermission(activity)
    }

    private fun gattCallback(generation: Int): BluetoothGattCallback =
        object : BluetoothGattCallback() {
            private fun current(gatt: BluetoothGatt): Boolean {
                val pair = connectedDevice
                val selected = pair?.leftDevice?.gatt === gatt ||
                    pair?.rightDevice?.gatt === gatt
                if (generation == connectionGeneration && selected) {
                    return true
                }
                intentionalDisconnectAddresses.remove(gatt.device.address)
                try {
                    gatt.close()
                } catch (error: Exception) {
                    Log.w(LOG_TAG, "Stale GATT close failed", error)
                }
                return false
            }

            override fun onConnectionStateChange(
                gatt: BluetoothGatt,
                status: Int,
                newState: Int,
            ) {
                if (!current(gatt)) return
                when {
                    status != BluetoothGatt.GATT_SUCCESS -> {
                        handleDisconnected(gatt, "gatt_status_$status")
                    }
                    newState == BluetoothProfile.STATE_CONNECTED -> {
                        if (!gatt.discoverServices()) {
                            handleDisconnected(
                                gatt,
                                "service_discovery_not_started",
                            )
                        }
                    }
                    newState == BluetoothProfile.STATE_DISCONNECTED -> {
                        handleDisconnected(gatt, "link_disconnected")
                    }
                }
            }

            override fun onServicesDiscovered(gatt: BluetoothGatt, status: Int) {
                if (!current(gatt)) return
                if (status != BluetoothGatt.GATT_SUCCESS) {
                    handleDisconnected(gatt, "service_discovery_failed_$status")
                    return
                }
                val pair = connectedDevice ?: return
                val isLeft = pair.leftDevice?.gatt === gatt
                val isRight = pair.rightDevice?.gatt === gatt
                if (!isLeft && !isRight) return

                val service = gatt.getService(UUID.fromString(SERVICE_UUID))
                val readCharacteristic = service?.getCharacteristic(
                    UUID.fromString(READ_CHARACTERISTIC_UUID),
                )
                val writeCharacteristic = service?.getCharacteristic(
                    UUID.fromString(WRITE_CHARACTERISTIC_UUID),
                )
                val descriptor = readCharacteristic?.getDescriptor(
                    UUID.fromString(CLIENT_CONFIGURATION_UUID),
                )
                if (readCharacteristic == null ||
                    writeCharacteristic == null ||
                    descriptor == null ||
                    !gatt.setCharacteristicNotification(readCharacteristic, true)
                ) {
                    handleDisconnected(gatt, "gatt_contract_incomplete")
                    return
                }

                if (isLeft) {
                    pair.leftDevice?.writeCharacteristic = writeCharacteristic
                } else {
                    pair.rightDevice?.writeCharacteristic = writeCharacteristic
                }

                val started = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                    gatt.writeDescriptor(
                        descriptor,
                        BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE,
                    ) == BluetoothGatt.GATT_SUCCESS
                } else {
                    @Suppress("DEPRECATION")
                    descriptor.value = BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE
                    @Suppress("DEPRECATION")
                    gatt.writeDescriptor(descriptor)
                }
                if (!started) {
                    handleDisconnected(gatt, "notification_descriptor_not_started")
                }
            }

            override fun onDescriptorWrite(
                gatt: BluetoothGatt,
                descriptor: BluetoothGattDescriptor,
                status: Int,
            ) {
                if (!current(gatt)) return
                if (descriptor.uuid != UUID.fromString(CLIENT_CONFIGURATION_UUID)) {
                    return
                }
                if (status != BluetoothGatt.GATT_SUCCESS) {
                    handleDisconnected(
                        gatt,
                        "notification_descriptor_failed_$status",
                    )
                    return
                }
                notificationReadyAddresses.add(gatt.device.address)
                if (!gatt.requestMtu(REQUESTED_MTU)) {
                    handleDisconnected(gatt, "mtu_request_not_started")
                }
            }

            override fun onMtuChanged(
                gatt: BluetoothGatt,
                mtu: Int,
                status: Int,
            ) {
                if (!current(gatt)) return
                if (status != BluetoothGatt.GATT_SUCCESS ||
                    mtu < REQUIRED_MTU ||
                    !notificationReadyAddresses.contains(gatt.device.address)
                ) {
                    handleDisconnected(gatt, "mtu_contract_failed_${status}_$mtu")
                    return
                }
                markReady(gatt)
            }

            @Deprecated("Deprecated in Android 13")
            override fun onCharacteristicChanged(
                gatt: BluetoothGatt,
                characteristic: BluetoothGattCharacteristic,
            ) {
                if (!current(gatt)) return
                @Suppress("DEPRECATION")
                handleCharacteristic(gatt, characteristic.value ?: return)
            }

            override fun onCharacteristicChanged(
                gatt: BluetoothGatt,
                characteristic: BluetoothGattCharacteristic,
                value: ByteArray,
            ) {
                if (!current(gatt)) return
                handleCharacteristic(gatt, value)
            }
        }

    private fun markReady(gatt: BluetoothGatt) {
        val pair = connectedDevice ?: return
        val address = gatt.device.address
        val device = when {
            pair.leftDevice?.gatt === gatt -> pair.leftDevice
            pair.rightDevice?.gatt === gatt -> pair.rightDevice
            else -> null
        } ?: return
        if (readyAddresses.contains(address)) return

        if (!device.writeInitialization(byteArrayOf(0xf4.toByte(), 0x01))) {
            handleDisconnected(gatt, "initialization_write_not_accepted")
            return
        }
        readyAddresses.add(address)

        if (pair.isBothConnected() && readyAddresses.size == 2) {
            val generation = connectionGeneration
            val pairIdentity = currentPairIdentity
            weakActivity.get()?.runOnUiThread {
                if (pair === connectedDevice &&
                    generation == connectionGeneration &&
                    pairIdentity == currentPairIdentity
                ) {
                    BleChannelHelper.bleMC.flutterGlassesConnected(
                        pair.toConnectedJson() +
                            mapOf(
                                "left_connected" to true,
                                "right_connected" to true,
                                "generation" to generation,
                                "pairIdentity" to pairIdentity,
                            ),
                    )
                }
            }
        }
    }

    private fun handleCharacteristic(gatt: BluetoothGatt, value: ByteArray) {
        if (value.isEmpty()) return
        val pair = connectedDevice ?: return
        val side = when {
            pair.leftDevice?.gatt === gatt -> "L"
            pair.rightDevice?.gatt === gatt -> "R"
            else -> return
        }
        val frame = value.copyOf()
        val generation = connectionGeneration
        val pairIdentity = currentPairIdentity

        decodeScope.launch {
            val microphoneData = frame[0] == 0xF1.toByte()
            if (microphoneData) {
                if (frame.size != 202) return@launch
                Cpp.decodeLC3(frame.copyOfRange(2, 202))
            }
            if (generation != connectionGeneration ||
                pairIdentity != currentPairIdentity
            ) return@launch
            weakActivity.get()?.runOnUiThread {
                if (generation != connectionGeneration ||
                    pairIdentity != currentPairIdentity
                ) return@runOnUiThread
                BleChannelHelper.bleReceive(
                    mapOf(
                        "lr" to side,
                        "data" to frame,
                        "type" to if (microphoneData) "VoiceChunk" else "Receive",
                        "generation" to generation,
                        "pairIdentity" to pairIdentity,
                    ),
                )
            }
        }
    }

    private fun sendToSide(data: ByteArray, left: Boolean): Boolean {
        val device = if (left) {
            connectedDevice?.leftDevice
        } else {
            connectedDevice?.rightDevice
        }
        return device?.isConnect == true && device.sendData(data)
    }

    private fun handleDisconnected(gatt: BluetoothGatt, reason: String) {
        if (intentionalDisconnectAddresses.remove(gatt.device.address)) {
            closeGatt(gatt)
            return
        }
        val pair = connectedDevice
        notificationReadyAddresses.remove(gatt.device.address)
        readyAddresses.remove(gatt.device.address)
        val side = when {
            pair?.leftDevice?.gatt === gatt -> {
                pair.leftDevice?.writeCharacteristic = null
                pair.leftDevice?.gatt = null
                pair.leftDevice?.isConnect = false
                "L"
            }
            pair?.rightDevice?.gatt === gatt -> {
                pair.rightDevice?.writeCharacteristic = null
                pair.rightDevice?.gatt = null
                pair.rightDevice?.isConnect = false
                "R"
            }
            else -> "unknown"
        }
        closeGatt(gatt)
        notifyDisconnected(reason, side, pair, currentPairIdentity)
    }

    private fun closeGatt(gatt: BluetoothGatt) {
        try {
            gatt.close()
        } catch (error: Exception) {
            Log.w(LOG_TAG, "GATT close failed", error)
        }
    }

    private fun disconnectCurrent(notifyFlutter: Boolean) {
        val pair = connectedDevice
        val pairIdentity = currentPairIdentity
        if (pair == null) {
            notificationReadyAddresses.clear()
            readyAddresses.clear()
            currentPairIdentity = UNSELECTED_PAIR
            return
        }
        pair.leftDevice?.address?.let(intentionalDisconnectAddresses::add)
        pair.rightDevice?.address?.let(intentionalDisconnectAddresses::add)
        pair.leftDevice?.disconnectAndClose()
        pair.rightDevice?.disconnectAndClose()
        notificationReadyAddresses.clear()
        readyAddresses.clear()
        connectedDevice = null
        if (notifyFlutter) {
            notifyDisconnected("user_requested", "both", pair, pairIdentity)
        }
        currentPairIdentity = UNSELECTED_PAIR
    }

    private fun notifyDisconnected(
        reason: String,
        side: String,
        snapshot: BlePairDevice? = connectedDevice,
        pairIdentity: String = currentPairIdentity,
    ) {
        val pair = snapshot
        val generation = connectionGeneration
        weakActivity.get()?.runOnUiThread {
            BleChannelHelper.bleMC.flutterGlassesDisconnected(
                mapOf(
                    "leftDeviceName" to (pair?.leftDevice?.name ?: ""),
                    "rightDeviceName" to (pair?.rightDevice?.name ?: ""),
                    "reason" to reason,
                    "side" to side,
                    "left_connected" to (pair?.leftDevice?.isConnect == true),
                    "right_connected" to (pair?.rightDevice?.isConnect == true),
                    "generation" to generation,
                    "pairIdentity" to pairIdentity,
                ),
            )
        }
    }
}
