package org.trillionnium.heptaglasses.model

import org.junit.Assert.assertFalse
import org.trillionnium.heptaglasses.bluetooth.BleMtuContract
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

    @Test
    fun fixed202ByteNotificationRequiresMtu205() {
        assertFalse(BleMtuContract.admits(203))
        assertFalse(BleMtuContract.admits(204))
        assertTrue(BleMtuContract.admits(205))
        assertTrue(BleMtuContract.admits(251))
    }
}
