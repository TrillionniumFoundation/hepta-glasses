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
import kotlinx.coroutines.MainScope
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

        val instance: BleManager by lazy { BleManager() }
    }

    private lateinit var weakActivity: WeakReference<Activity>
    private lateinit var bluetoothManager: BluetoothManager
    private val bluetoothAdapter
        get() = bluetoothManager.adapter
    private val discoveredDevices: MutableList<BleDevice> = mutableListOf()
    private var connectedDevice: BlePairDevice? = null
    private val readyAddresses: MutableSet<String> = mutableSetOf()
    private val intentionalDisconnectAddresses: MutableSet<String> = mutableSetOf()
    private var connectionGeneration = 0
    private val mainScope: CoroutineScope = MainScope()

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
        readyAddresses.clear()
        connectedDevice = BlePairDevice(left, right)
        BleChannelHelper.bleMC.flutterGlassesConnecting(
            mapOf(
                "leftDeviceName" to left.name,
                "rightDeviceName" to right.name,
                "generation" to connectionGeneration,
            ),
        )
        val activity = weakActivity.get()
        if (activity == null) {
            result.error("ActivityUnavailable", "Activity is unavailable", null)
            return
        }
        val generation = connectionGeneration
        bluetoothAdapter.getRemoteDevice(left.address)
            .connectGatt(activity, false, gattCallback(generation))
        bluetoothAdapter.getRemoteDevice(right.address)
            .connectGatt(activity, false, gattCallback(generation))
        result.success("Connecting to G1_$deviceChannel ...")
    }

    fun disconnectFromGlasses(result: MethodChannel.Result) {
        disconnectCurrent(notifyFlutter = true)
        result.success("Disconnected all devices.")
    }

    fun sendData(params: Map<*, *>?): Boolean {
        val rawData = params?.get("data")
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
            if (generation == connectionGeneration) {
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
                        handleDisconnected(gatt, "service_discovery_not_started")
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
            val isLeft = gatt.device.address == pair.leftDevice?.address
            val isRight = gatt.device.address == pair.rightDevice?.address
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
                pair.update(leftGatt = gatt)
                pair.leftDevice?.writeCharacteristic = writeCharacteristic
            } else {
                pair.update(rightGatt = gatt)
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
                handleDisconnected(gatt, "notification_descriptor_failed_$status")
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
        val isLeft = address == pair.leftDevice?.address
        val isRight = address == pair.rightDevice?.address
        if (!isLeft && !isRight) return

        readyAddresses.add(address)
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
            weakActivity.get()?.runOnUiThread {
                BleChannelHelper.bleMC.flutterGlassesConnected(
                    pair.toConnectedJson() +
                        mapOf(
                            "left_connected" to true,
                            "right_connected" to true,
                            "generation" to connectionGeneration,
                        ),
                )
            }
        }
    }

    private fun handleCharacteristic(gatt: BluetoothGatt, value: ByteArray) {
        if (value.isEmpty()) return
        val pair = connectedDevice ?: return
        val isLeft = gatt.device.address == pair.leftDevice?.address
        val isRight = gatt.device.address == pair.rightDevice?.address
        if (!isLeft && !isRight) return

        mainScope.launch {
            val microphoneData = value[0] == 0xF1.toByte()
            if (microphoneData) {
                if (value.size != 202) return@launch
                val lc3 = value.copyOfRange(2, 202)
                Cpp.decodeLC3(lc3)
            }
            BleChannelHelper.bleReceive(
                mapOf(
                    "lr" to if (isLeft) "L" else "R",
                    "data" to value,
                    "type" to if (microphoneData) "VoiceChunk" else "Receive",
                    "generation" to connectionGeneration,
                ),
            )
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
            try {
                gatt.close()
            } catch (error: Exception) {
                Log.w(LOG_TAG, "GATT close failed", error)
            }
            return
        }
        val pair = connectedDevice
        readyAddresses.remove(gatt.device.address)
        when (gatt.device.address) {
            pair?.leftDevice?.address -> pair.update(isLeftConnect = false)
            pair?.rightDevice?.address -> pair.update(isRightConnected = false)
        }
        try {
            gatt.close()
        } catch (error: Exception) {
            Log.w(LOG_TAG, "GATT close failed", error)
        }
        notifyDisconnected(
            reason,
            when (gatt.device.address) {
                pair?.leftDevice?.address -> "L"
                pair?.rightDevice?.address -> "R"
                else -> "unknown"
            },
        )
    }

    private fun disconnectCurrent(notifyFlutter: Boolean) {
        val pair = connectedDevice ?: return
        pair.leftDevice?.address?.let(intentionalDisconnectAddresses::add)
        pair.rightDevice?.address?.let(intentionalDisconnectAddresses::add)
        pair.leftDevice?.disconnectAndClose()
        pair.rightDevice?.disconnectAndClose()
        readyAddresses.clear()
        connectedDevice = null
        if (notifyFlutter) notifyDisconnected("user_requested", "both", pair)
    }

    private fun notifyDisconnected(
        reason: String,
        side: String,
        snapshot: BlePairDevice? = connectedDevice,
    ) {
        val pair = snapshot
        weakActivity.get()?.runOnUiThread {
            BleChannelHelper.bleMC.flutterGlassesDisconnected(
                mapOf(
                    "leftDeviceName" to (pair?.leftDevice?.name ?: ""),
                    "rightDeviceName" to (pair?.rightDevice?.name ?: ""),
                    "reason" to reason,
                    "side" to side,
                    "left_connected" to (pair?.leftDevice?.isConnect == true),
                    "right_connected" to (pair?.rightDevice?.isConnect == true),
                    "generation" to connectionGeneration,
                ),
            )
        }
    }
}
