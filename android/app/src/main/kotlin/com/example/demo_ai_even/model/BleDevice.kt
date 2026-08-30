package com.example.demo_ai_even.model

import android.annotation.SuppressLint
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCharacteristic
import android.os.Build
import android.util.Log
import com.example.demo_ai_even.bluetooth.BleManager

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
        fun createByDevice(
            name: String,
            address: String,
            channelNumber: String,
        ) = BleDevice(name, address, null, null, false, channelNumber)
    }

    fun isLeft() = name.contains("_L_")

    fun isRight() = name.contains("_R_")

    fun sendData(data: ByteArray): Boolean {
        val currentGatt = gatt
        val characteristic = writeCharacteristic
        if (currentGatt == null || characteristic == null) {
            Log.e(BleManager.LOG_TAG, "$name: GATT is not ready")
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
