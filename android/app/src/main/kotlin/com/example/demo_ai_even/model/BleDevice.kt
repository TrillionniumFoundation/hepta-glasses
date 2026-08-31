package com.example.demo_ai_even.model

import android.annotation.SuppressLint
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCharacteristic
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.util.Log
import com.example.demo_ai_even.bluetooth.BleManager
import com.example.demo_ai_even.bluetooth.BoundedWriteQueue

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
    private val writeHandler = Handler(Looper.getMainLooper())

    @Volatile
    private var drainScheduled = false

    fun isLeft() = name.contains("_L_")

    fun isRight() = name.contains("_R_")

    fun writeInitialization(data: ByteArray): Boolean {
        if (data.isEmpty() || gatt == null || writeCharacteristic == null) {
            return false
        }
        val accepted = writeNow(data, requireReady = false)
        if (accepted) {
            isConnect = true
        }
        return accepted
    }

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
        writeHandler.post(::drainOne)
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

        if (!writeNow(payload, requireReady = true)) {
            writeQueue.clear()
            synchronized(this) {
                drainScheduled = false
            }
            return
        }
        writeHandler.postDelayed(::drainOne, WRITE_INTERVAL_MS)
    }

    private fun writeNow(data: ByteArray, requireReady: Boolean): Boolean {
        val currentGatt = gatt
        val characteristic = writeCharacteristic
        if (currentGatt == null ||
            characteristic == null ||
            (requireReady && !isConnect)
        ) {
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
        writeHandler.removeCallbacksAndMessages(null)
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
