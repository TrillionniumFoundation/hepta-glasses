package com.example.demo_ai_even.speech

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class AndroidPcmAsrTest {
    private fun ticket() = SpeechTicket(
        sessionId = "session",
        generation = 7,
        pairIdentity = "Pair_1",
        locale = "en-US",
        endpoint = "https://speech.example/v1/asr",
        bearerToken = "ephemeral-token-123456789",
        expiresAtEpochSeconds = 200,
        maximumAudioBytes = 6400,
    )

    @Test
    fun finalTranscriptIsGenerationAndPairBound() {
        var calls = 0
        val recognizer = AndroidPcmAsr(ticket(), SpeechTransport { _, pcm ->
            calls += 1
            assertEquals(4, pcm.size)
            "hello"
        }) { 100 }
        recognizer.append(byteArrayOf(1, 0, 2, 0), 7, "Pair_1")
        assertEquals("hello", recognizer.finalizeTranscript(7, "Pair_1"))
        assertEquals(1, calls)
        assertThrows(IllegalStateException::class.java) {
            recognizer.finalizeTranscript(7, "Pair_1")
        }
    }

    @Test
    fun staleGenerationAndCancellationFailClosed() {
        val recognizer = AndroidPcmAsr(ticket(), SpeechTransport { _, _ -> "never" }) { 100 }
        assertThrows(IllegalStateException::class.java) {
            recognizer.append(byteArrayOf(1, 0), 6, "Pair_1")
        }
        recognizer.append(byteArrayOf(1, 0), 7, "Pair_1")
        recognizer.cancel()
        assertThrows(IllegalStateException::class.java) {
            recognizer.finalizeTranscript(7, "Pair_1")
        }
    }

    @Test
    fun boundedAudioRejectsOverflow() {
        val recognizer = AndroidPcmAsr(ticket(), SpeechTransport { _, _ -> "never" }) { 100 }
        assertThrows(IllegalStateException::class.java) {
            recognizer.append(ByteArray(6402), 7, "Pair_1")
        }
    }
}
