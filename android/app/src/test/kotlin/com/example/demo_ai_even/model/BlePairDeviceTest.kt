package com.example.demo_ai_even.model

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class BlePairDeviceTest {
    @Test
    fun readinessRequiresBothLegs() {
        val left = BleDevice.createByDevice("G1_01_L_test", "left", "01")
        val right = BleDevice.createByDevice("G1_01_R_test", "right", "01")
        val pair = BlePairDevice(left, right)

        assertFalse(pair.isBothConnected())
        pair.update(isLeftConnect = true)
        assertFalse(pair.isBothConnected())
        pair.update(isRightConnected = true)
        assertTrue(pair.isBothConnected())
    }
}
