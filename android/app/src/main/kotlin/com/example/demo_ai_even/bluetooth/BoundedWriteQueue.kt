package com.example.demo_ai_even.bluetooth

import java.util.ArrayDeque

internal class BoundedWriteQueue(private val capacity: Int = 128) {
    init {
        require(capacity > 0) { "capacity must be positive" }
    }

    private val queue = ArrayDeque<ByteArray>()

    @Synchronized
    fun offer(data: ByteArray): Boolean {
        if (data.isEmpty() || queue.size >= capacity) return false
        queue.addLast(data.copyOf())
        return true
    }

    @Synchronized
    fun poll(): ByteArray? = queue.pollFirst()

    @Synchronized
    fun clear() {
        queue.clear()
    }

    @Synchronized
    fun size(): Int = queue.size
}
