package com.example.demo_ai_even.bluetooth

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class BoundedWriteQueueTest {
    @Test
    fun queueIsBoundedAndCopiesPayloads() {
        val queue = BoundedWriteQueue(capacity = 2)
        val first = byteArrayOf(1, 2)

        assertTrue(queue.offer(first))
        first[0] = 9
        assertTrue(queue.offer(byteArrayOf(3)))
        assertFalse(queue.offer(byteArrayOf(4)))
        assertEquals(2, queue.size())

        val firstOut = queue.poll()
        val secondOut = queue.poll()
        assertNotNull(firstOut)
        assertNotNull(secondOut)
        assertArrayEquals(byteArrayOf(1, 2), firstOut!!)
        assertArrayEquals(byteArrayOf(3), secondOut!!)
        assertNull(queue.poll())
    }

    @Test
    fun emptyPayloadIsRejectedAndClearIsDeterministic() {
        val queue = BoundedWriteQueue(capacity = 1)

        assertFalse(queue.offer(byteArrayOf()))
        assertTrue(queue.offer(byteArrayOf(7)))
        queue.clear()
        assertEquals(0, queue.size())
        assertNull(queue.poll())
    }
}
