package com.example.demo_ai_even.speech

import java.io.ByteArrayOutputStream
import java.net.URI
import javax.net.ssl.HttpsURLConnection

internal data class SpeechTicket(
    val sessionId: String,
    val generation: Int,
    val connectionGeneration: Int,
    val pairIdentity: String,
    val locale: String,
    val endpoint: String,
    val bearerToken: String,
    val expiresAtEpochSeconds: Long,
    val maximumAudioBytes: Int,
)

internal fun interface SpeechTransport {
    fun recognize(ticket: SpeechTicket, pcm: ByteArray): String
}

internal class HttpsSpeechTransport : SpeechTransport {
    override fun recognize(ticket: SpeechTicket, pcm: ByteArray): String {
        val uri = URI(ticket.endpoint)
        require(uri.scheme == "https" && uri.host != null && uri.userInfo == null && uri.fragment == null) {
            "SpeechEndpointInvalid"
        }
        val connection = uri.toURL().openConnection() as HttpsURLConnection
        connection.instanceFollowRedirects = false
        connection.connectTimeout = 8_000
        connection.readTimeout = 20_000
        connection.requestMethod = "POST"
        connection.doOutput = true
        connection.setRequestProperty("Authorization", "Bearer ${ticket.bearerToken}")
        connection.setRequestProperty("Content-Type", "audio/L16;rate=16000;channels=1")
        connection.setRequestProperty("Accept", "application/json")
        connection.setRequestProperty("X-Hepta-Session", ticket.sessionId)
        connection.setRequestProperty("X-Hepta-Generation", ticket.generation.toString())
        connection.setRequestProperty(
            "X-Hepta-Connection-Generation",
            ticket.connectionGeneration.toString(),
        )
        connection.setRequestProperty("X-Hepta-Pair", ticket.pairIdentity)
        connection.setRequestProperty("X-Hepta-Locale", ticket.locale)
        connection.outputStream.use { it.write(pcm) }
        val code = connection.responseCode
        if (code !in 200..299) {
            connection.disconnect()
            throw IllegalStateException("SpeechProviderRejected")
        }
        if (connection.getHeaderField("Location") != null) {
            connection.disconnect()
            throw IllegalStateException("SpeechRedirectRejected")
        }
        val raw = connection.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() }
        connection.disconnect()
        if (raw.length > 32_768) throw IllegalStateException("SpeechResponseTooLarge")
        val match = Regex("\\\"(?:text|transcript)\\\"\\s*:\\s*\\\"((?:\\\\.|[^\\\"])*)\\\"").find(raw)
            ?: throw IllegalStateException("SpeechResponseInvalid")
        return match.groupValues[1]
            .replace("\\\\\"", "\"")
            .replace("\\\\n", "\n")
            .replace("\\\\\\\\", "\\")
            .trim()
    }
}

internal class AndroidPcmAsr(
    private val ticket: SpeechTicket,
    private val transport: SpeechTransport = HttpsSpeechTransport(),
    private val nowEpochSeconds: () -> Long = { System.currentTimeMillis() / 1000L },
) {
    private val buffer = ByteArrayOutputStream()
    private var cancelled = false
    private var finalized = false

    init {
        require(ticket.sessionId.isNotBlank()) { "SpeechSessionInvalid" }
        require(ticket.generation > 0) { "SpeechGenerationInvalid" }
        require(ticket.connectionGeneration > 0) {
            "SpeechConnectionGenerationInvalid"
        }
        require(ticket.pairIdentity.isNotBlank()) { "SpeechPairInvalid" }
        require(ticket.locale.matches(Regex("[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})?"))) { "SpeechLocaleInvalid" }
        require(ticket.endpoint.startsWith("https://")) { "SpeechEndpointInvalid" }
        require(ticket.bearerToken.length >= 16) { "SpeechTokenInvalid" }
        require(ticket.maximumAudioBytes in 3_200..1_920_000) { "SpeechAudioLimitInvalid" }
        require(ticket.expiresAtEpochSeconds > nowEpochSeconds()) { "SpeechTicketExpired" }
        require(ticket.expiresAtEpochSeconds - nowEpochSeconds() <= 300L) { "SpeechTicketTooLong" }
    }

    @Synchronized
    fun append(pcm: ByteArray, generation: Int, pairIdentity: String) {
        check(!cancelled && !finalized) { "SpeechSessionInactive" }
        check(generation == ticket.generation && pairIdentity == ticket.pairIdentity) { "SpeechAuthorityStale" }
        if (pcm.isEmpty() || pcm.size % 2 != 0) throw IllegalArgumentException("SpeechPcmInvalid")
        if (buffer.size() + pcm.size > ticket.maximumAudioBytes) throw IllegalStateException("SpeechAudioLimitExceeded")
        buffer.write(pcm)
    }

    @Synchronized
    fun cancel() {
        cancelled = true
        buffer.reset()
    }

    fun finalizeTranscript(generation: Int, pairIdentity: String): String {
        val pcm: ByteArray
        synchronized(this) {
            check(!cancelled && !finalized) { "SpeechSessionInactive" }
            check(generation == ticket.generation && pairIdentity == ticket.pairIdentity) { "SpeechAuthorityStale" }
            check(nowEpochSeconds() < ticket.expiresAtEpochSeconds) { "SpeechTicketExpired" }
            check(buffer.size() > 0) { "SpeechAudioEmpty" }
            finalized = true
            pcm = buffer.toByteArray()
            buffer.reset()
        }
        return transport.recognize(ticket, pcm)
    }
}
