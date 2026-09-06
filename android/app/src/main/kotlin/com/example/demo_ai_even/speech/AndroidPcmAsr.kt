package com.example.demo_ai_even.speech

import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.InputStream
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
        require(
            uri.scheme == "https" &&
                uri.host != null &&
                uri.userInfo == null &&
                uri.fragment == null &&
                (uri.port == -1 || uri.port == 443),
        ) { "SpeechEndpointInvalid" }
        val connection = uri.toURL().openConnection() as HttpsURLConnection
        try {
            connection.instanceFollowRedirects = false
            connection.connectTimeout = 8_000
            connection.readTimeout = 20_000
            connection.requestMethod = "POST"
            connection.doOutput = true
            connection.setRequestProperty(
                "Authorization",
                "Bearer ${ticket.bearerToken}",
            )
            connection.setRequestProperty(
                "Content-Type",
                "audio/L16;rate=16000;channels=1",
            )
            connection.setRequestProperty("Accept", "application/json")
            connection.setRequestProperty("X-Hepta-Session", ticket.sessionId)
            connection.setRequestProperty(
                "X-Hepta-Generation",
                ticket.generation.toString(),
            )
            connection.setRequestProperty(
                "X-Hepta-Connection-Generation",
                ticket.connectionGeneration.toString(),
            )
            connection.setRequestProperty("X-Hepta-Pair", ticket.pairIdentity)
            connection.setRequestProperty("X-Hepta-Locale", ticket.locale)
            connection.outputStream.use { it.write(pcm) }

            val code = connection.responseCode
            if (code !in 200..299) {
                throw IllegalStateException("SpeechProviderRejected")
            }
            if (connection.getHeaderField("Location") != null) {
                throw IllegalStateException("SpeechRedirectRejected")
            }
            val contentType = connection.contentType
                ?.substringBefore(';')
                ?.trim()
                ?.lowercase()
            if (contentType != "application/json") {
                throw IllegalStateException("SpeechResponseTypeInvalid")
            }
            val declaredLength = connection.contentLengthLong
            if (declaredLength > MAX_RESPONSE_BYTES) {
                throw IllegalStateException("SpeechResponseTooLarge")
            }
            val raw = readBounded(connection.inputStream, MAX_RESPONSE_BYTES)
            return parseFinalResponse(raw, ticket)
        } finally {
            connection.disconnect()
        }
    }

    internal fun parseFinalResponse(raw: String, ticket: SpeechTicket): String {
        if (raw.toByteArray(Charsets.UTF_8).size > MAX_RESPONSE_BYTES) {
            throw IllegalStateException("SpeechResponseTooLarge")
        }
        val document = try {
            JSONObject(raw)
        } catch (_: Exception) {
            throw IllegalStateException("SpeechResponseInvalid")
        }
        val required = setOf(
            "session_id",
            "generation",
            "connection_generation",
            "pair_identity",
            "is_final",
            "transcript",
        )
        val actual = document.keys().asSequence().toSet()
        if (actual != required || required.any { key -> keyCount(raw, key) != 1 }) {
            throw IllegalStateException("SpeechResponseInvalid")
        }
        val sessionId = document.optString("session_id", "")
        val pairIdentity = document.optString("pair_identity", "")
        val transcript = document.optString("transcript", "").trim()
        if (sessionId != ticket.sessionId ||
            document.optInt("generation", -1) != ticket.generation ||
            document.optInt("connection_generation", -1) !=
            ticket.connectionGeneration ||
            pairIdentity != ticket.pairIdentity ||
            !document.optBoolean("is_final", false) ||
            transcript.isEmpty() ||
            transcript.toByteArray(Charsets.UTF_8).size > MAX_TRANSCRIPT_BYTES
        ) {
            throw IllegalStateException("SpeechResponseBindingInvalid")
        }
        return transcript
    }

    private fun keyCount(raw: String, key: String): Int =
        Regex("(?<!\\\\)\\\"${Regex.escape(key)}\\\"\\s*:")
            .findAll(raw)
            .count()

    private fun readBounded(input: InputStream, maximum: Int): String {
        val output = ByteArrayOutputStream()
        val chunk = ByteArray(4096)
        input.use { stream ->
            while (true) {
                val count = stream.read(chunk)
                if (count < 0) break
                if (count == 0) continue
                if (output.size() + count > maximum) {
                    throw IllegalStateException("SpeechResponseTooLarge")
                }
                output.write(chunk, 0, count)
            }
        }
        return try {
            output.toByteArray().toString(Charsets.UTF_8)
        } catch (_: Exception) {
            throw IllegalStateException("SpeechResponseInvalid")
        }
    }

    private companion object {
        const val MAX_RESPONSE_BYTES = 32_768
        const val MAX_TRANSCRIPT_BYTES = 8_192
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
        require(
            ticket.bearerToken.length in 16..8192 &&
                ticket.bearerToken.all { character ->
                    character.code in 33..126
                },
        ) { "SpeechTokenInvalid" }
        require(ticket.maximumAudioBytes in 3_200..1_920_000) { "SpeechAudioLimitInvalid" }
        val now = nowEpochSeconds()
        require(ticket.expiresAtEpochSeconds > now) { "SpeechTicketExpired" }
        require(ticket.expiresAtEpochSeconds - now <= 300L) { "SpeechTicketTooLong" }
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
