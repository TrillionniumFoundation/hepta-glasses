package com.example.demo_ai_even.speech

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class AndroidPcmAsrTest {
    private fun ticket() = SpeechTicket(
        sessionId = "session",
        generation = 7,
        connectionGeneration = 11,
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
        val recognizer = AndroidPcmAsr(ticket(), SpeechTransport { receivedTicket, pcm ->
            calls += 1
            assertEquals(4, pcm.size)
            assertEquals(7, receivedTicket.generation)
            assertEquals(11, receivedTicket.connectionGeneration)
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

    @Test
    fun invalidConnectionGenerationIsRejected() {
        assertThrows(IllegalArgumentException::class.java) {
            AndroidPcmAsr(ticket().copy(connectionGeneration = 0)) { 100 }
        }
    }

    @Test
    fun providerFinalResponseMustBindEveryAuthorityDimension() {
        val transport = HttpsSpeechTransport()
        val valid = """{
            "session_id":"session",
            "generation":7,
            "connection_generation":11,
            "pair_identity":"Pair_1",
            "is_final":true,
            "transcript":"hello"
        }""".trimIndent()
        assertEquals("hello", transport.parseFinalResponse(valid, ticket()))

        val staleConnection = valid.replace(
            "\"connection_generation\":11",
            "\"connection_generation\":12",
        )
        assertThrows(IllegalStateException::class.java) {
            transport.parseFinalResponse(staleConnection, ticket())
        }
        val duplicateGeneration = valid.replace(
            "\"generation\":7,",
            "\"generation\":7,\"generation\":7,",
        )
        assertThrows(IllegalStateException::class.java) {
            transport.parseFinalResponse(duplicateGeneration, ticket())
        }
    }

    @Test
    fun providerFinalResponseRejectsPartialOrUnknownFields() {
        val transport = HttpsSpeechTransport()
        val partial = """{
            "session_id":"session",
            "generation":7,
            "connection_generation":11,
            "pair_identity":"Pair_1",
            "is_final":false,
            "transcript":"partial"
        }""".trimIndent()
        assertThrows(IllegalStateException::class.java) {
            transport.parseFinalResponse(partial, ticket())
        }
        val widened = partial
            .replace("\"is_final\":false", "\"is_final\":true")
            .dropLast(1) + ",\"tool_call\":true}"
        assertThrows(IllegalStateException::class.java) {
            transport.parseFinalResponse(widened, ticket())
        }
    }
}
