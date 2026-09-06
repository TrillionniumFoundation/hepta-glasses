package com.example.demo_ai_even.speech

import java.io.ByteArrayOutputStream
import java.io.InputStream
import java.net.URI
import java.nio.ByteBuffer
import java.nio.charset.CodingErrorAction
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
        val document = StrictSpeechJson(raw).parseObject()
        val required = setOf(
            "session_id",
            "generation",
            "connection_generation",
            "pair_identity",
            "is_final",
            "transcript",
        )
        if (document.keys != required) {
            throw IllegalStateException("SpeechResponseInvalid")
        }
        val transcript = (document["transcript"] as? String)?.trim()
            ?: throw IllegalStateException("SpeechResponseInvalid")
        if (document["session_id"] != ticket.sessionId ||
            document["generation"] != ticket.generation.toLong() ||
            document["connection_generation"] !=
            ticket.connectionGeneration.toLong() ||
            document["pair_identity"] != ticket.pairIdentity ||
            document["is_final"] != true ||
            transcript.isEmpty() ||
            transcript.toByteArray(Charsets.UTF_8).size > MAX_TRANSCRIPT_BYTES
        ) {
            throw IllegalStateException("SpeechResponseBindingInvalid")
        }
        return transcript
    }

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
            Charsets.UTF_8.newDecoder()
                .onMalformedInput(CodingErrorAction.REPORT)
                .onUnmappableCharacter(CodingErrorAction.REPORT)
                .decode(ByteBuffer.wrap(output.toByteArray()))
                .toString()
        } catch (_: Exception) {
            throw IllegalStateException("SpeechResponseInvalid")
        }
    }

    private companion object {
        const val MAX_RESPONSE_BYTES = 32_768
        const val MAX_TRANSCRIPT_BYTES = 8_192
    }
}

/** A deliberately small JSON reader for the fixed speech-final response. */
private class StrictSpeechJson(private val source: String) {
    private var offset = 0

    fun parseObject(): Map<String, Any> {
        skipWhitespace()
        expect('{')
        skipWhitespace()
        val result = linkedMapOf<String, Any>()
        if (take('}')) {
            finish()
            return result
        }
        while (true) {
            val key = parseString()
            if (result.containsKey(key)) fail()
            skipWhitespace()
            expect(':')
            skipWhitespace()
            result[key] = parseValue()
            skipWhitespace()
            if (take('}')) break
            expect(',')
            skipWhitespace()
        }
        finish()
        return result
    }

    private fun parseValue(): Any = when (peek()) {
        '"' -> parseString()
        't' -> {
            expectLiteral("true")
            true
        }
        'f' -> {
            expectLiteral("false")
            false
        }
        in '0'..'9' -> parseInteger()
        else -> fail()
    }

    private fun parseInteger(): Long {
        val start = offset
        if (peek() == '0') {
            offset += 1
            if (peekOrNull()?.isDigit() == true) fail()
        } else {
            while (peekOrNull()?.isDigit() == true) offset += 1
        }
        return source.substring(start, offset).toLongOrNull() ?: fail()
    }

    private fun parseString(): String {
        expect('"')
        val output = StringBuilder()
        while (true) {
            val character = peekOrNull() ?: fail()
            offset += 1
            when {
                character == '"' -> return validateSurrogates(output.toString())
                character == '\\' -> output.append(parseEscape())
                character.code < 0x20 -> fail()
                else -> output.append(character)
            }
        }
    }

    private fun parseEscape(): Char {
        val escape = peekOrNull() ?: fail()
        offset += 1
        return when (escape) {
            '"', '\\', '/' -> escape
            'b' -> '\b'
            'f' -> '\u000C'
            'n' -> '\n'
            'r' -> '\r'
            't' -> '\t'
            'u' -> {
                if (offset + 4 > source.length) fail()
                val value = source.substring(offset, offset + 4)
                    .toIntOrNull(16) ?: fail()
                offset += 4
                value.toChar()
            }
            else -> fail()
        }
    }

    private fun validateSurrogates(value: String): String {
        var index = 0
        while (index < value.length) {
            val current = value[index]
            when {
                current.isHighSurrogate() -> {
                    if (index + 1 >= value.length ||
                        !value[index + 1].isLowSurrogate()
                    ) {
                        fail()
                    }
                    index += 2
                }
                current.isLowSurrogate() -> fail()
                else -> index += 1
            }
        }
        return value
    }

    private fun expectLiteral(value: String) {
        if (!source.startsWith(value, offset)) fail()
        offset += value.length
    }

    private fun finish() {
        skipWhitespace()
        if (offset != source.length) fail()
    }

    private fun skipWhitespace() {
        while (peekOrNull() in setOf(' ', '\n', '\r', '\t')) offset += 1
    }

    private fun expect(character: Char) {
        if (!take(character)) fail()
    }

    private fun take(character: Char): Boolean {
        if (peekOrNull() != character) return false
        offset += 1
        return true
    }

    private fun peek(): Char = peekOrNull() ?: fail()

    private fun peekOrNull(): Char? = source.getOrNull(offset)

    private fun fail(): Nothing =
        throw IllegalStateException("SpeechResponseInvalid")
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
        val identifier = Regex("[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
        require(identifier.matches(ticket.sessionId)) { "SpeechSessionInvalid" }
        require(ticket.generation > 0) { "SpeechGenerationInvalid" }
        require(ticket.connectionGeneration > 0) {
            "SpeechConnectionGenerationInvalid"
        }
        require(identifier.matches(ticket.pairIdentity)) { "SpeechPairInvalid" }
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
