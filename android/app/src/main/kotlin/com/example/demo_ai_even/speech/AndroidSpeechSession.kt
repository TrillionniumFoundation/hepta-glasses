package com.example.demo_ai_even.speech

import android.os.Handler
import android.os.Looper
import com.example.demo_ai_even.bluetooth.BleChannelHelper
import java.util.concurrent.Executors

/**
 * Process-local custody for one Android speech session.
 *
 * Provider output is bound to the assistant generation, while PCM ingress is
 * additionally bound to the exact BLE connection generation and pair identity.
 * It never persists audio, tokens or transcripts. Final provider work is
 * serialized off the Flutter/GATT threads, and a later start/cancel fences an
 * older result before EventChannel delivery.
 */
internal object AndroidSpeechSession {
    private val lock = Any()
    private val mainHandler = Handler(Looper.getMainLooper())
    private val finalizer = Executors.newSingleThreadExecutor { runnable ->
        Thread(runnable, "hepta-android-speech-finalizer").apply {
            isDaemon = true
        }
    }

    private var recognizer: AndroidPcmAsr? = null
    private var assistantGeneration: Int = 0
    private var connectionGeneration: Int = 0
    private var pairIdentity: String = ""
    private var epoch: Long = 0
    private var finalizing: Boolean = false

    fun start(ticket: SpeechTicket) {
        val next = AndroidPcmAsr(ticket)
        synchronized(lock) {
            recognizer?.cancel()
            epoch += 1
            recognizer = next
            assistantGeneration = ticket.generation
            connectionGeneration = ticket.connectionGeneration
            pairIdentity = ticket.pairIdentity
            finalizing = false
        }
    }

    fun append(
        pcm: ByteArray,
        expectedConnectionGeneration: Int,
        expectedPairIdentity: String,
    ) {
        val captured = synchronized(lock) {
            val active = recognizer
            if (active == null ||
                finalizing ||
                expectedConnectionGeneration != connectionGeneration ||
                expectedPairIdentity != pairIdentity
            ) {
                null
            } else {
                Triple(active, assistantGeneration, epoch)
            }
        } ?: return

        try {
            captured.first.append(
                pcm,
                captured.second,
                expectedPairIdentity,
            )
        } catch (_: IllegalArgumentException) {
            abort(
                captured.third,
                expectedConnectionGeneration,
                expectedPairIdentity,
                "SpeechPcmInvalid",
            )
        } catch (_: IllegalStateException) {
            abort(
                captured.third,
                expectedConnectionGeneration,
                expectedPairIdentity,
                "SpeechSessionInvalid",
            )
        }
    }

    fun stop(
        expectedAssistantGeneration: Int,
        expectedConnectionGeneration: Int,
        expectedPairIdentity: String,
        finalize: Boolean,
    ): Boolean {
        if (!finalize) {
            return cancel(
                expectedAssistantGeneration,
                expectedConnectionGeneration,
                expectedPairIdentity,
            )
        }

        val captured: Pair<AndroidPcmAsr, Long> = synchronized(lock) {
            val active = recognizer
            if (active == null ||
                finalizing ||
                expectedAssistantGeneration != assistantGeneration ||
                expectedConnectionGeneration != connectionGeneration ||
                expectedPairIdentity != pairIdentity
            ) {
                return false
            }
            finalizing = true
            active to epoch
        }

        finalizer.execute {
            try {
                val transcript = captured.first.finalizeTranscript(
                    expectedAssistantGeneration,
                    expectedPairIdentity,
                )
                completeIfCurrent(
                    captured.second,
                    expectedAssistantGeneration,
                    expectedConnectionGeneration,
                    expectedPairIdentity,
                    transcript,
                    null,
                )
            } catch (error: Exception) {
                completeIfCurrent(
                    captured.second,
                    expectedAssistantGeneration,
                    expectedConnectionGeneration,
                    expectedPairIdentity,
                    "",
                    when (error) {
                        is IllegalArgumentException -> "SpeechProviderResponseInvalid"
                        is IllegalStateException -> error.message
                            ?.takeIf { it.matches(Regex("[A-Za-z][A-Za-z0-9_]{0,63}")) }
                            ?: "SpeechRecognitionFailed"
                        else -> "SpeechRecognitionFailed"
                    },
                )
            }
        }
        return true
    }

    fun cancel(
        expectedAssistantGeneration: Int,
        expectedConnectionGeneration: Int,
        expectedPairIdentity: String,
    ): Boolean = synchronized(lock) {
        val active = recognizer
        if (active == null ||
            expectedAssistantGeneration != assistantGeneration ||
            expectedConnectionGeneration != connectionGeneration ||
            expectedPairIdentity != pairIdentity
        ) {
            return false
        }
        epoch += 1
        active.cancel()
        clearLocked()
        true
    }

    fun cancelCurrent() {
        synchronized(lock) {
            epoch += 1
            recognizer?.cancel()
            clearLocked()
        }
    }

    private fun abort(
        capturedEpoch: Long,
        expectedConnectionGeneration: Int,
        expectedPairIdentity: String,
        code: String,
    ) {
        val completedAssistantGeneration: Int? = synchronized(lock) {
            if (capturedEpoch != epoch ||
                expectedConnectionGeneration != connectionGeneration ||
                expectedPairIdentity != pairIdentity
            ) {
                null
            } else {
                val value = assistantGeneration
                epoch += 1
                recognizer?.cancel()
                clearLocked()
                value
            }
        }
        if (completedAssistantGeneration != null) {
            emitFinal(completedAssistantGeneration, "", code)
        }
    }

    private fun completeIfCurrent(
        capturedEpoch: Long,
        expectedAssistantGeneration: Int,
        expectedConnectionGeneration: Int,
        expectedPairIdentity: String,
        transcript: String,
        errorCode: String?,
    ) {
        val shouldEmit = synchronized(lock) {
            if (capturedEpoch != epoch ||
                expectedAssistantGeneration != assistantGeneration ||
                expectedConnectionGeneration != connectionGeneration ||
                expectedPairIdentity != pairIdentity ||
                !finalizing
            ) {
                false
            } else {
                clearLocked()
                true
            }
        }
        if (shouldEmit) {
            emitFinal(
                expectedAssistantGeneration,
                transcript.trim(),
                errorCode,
            )
        }
    }

    private fun clearLocked() {
        recognizer = null
        assistantGeneration = 0
        connectionGeneration = 0
        pairIdentity = ""
        finalizing = false
    }

    private fun emitFinal(
        completedAssistantGeneration: Int,
        transcript: String,
        errorCode: String?,
    ) {
        mainHandler.post {
            BleChannelHelper.bleSpeechRecognize(
                mapOf(
                    "script" to transcript,
                    "generation" to completedAssistantGeneration,
                    "is_final" to true,
                    "is_framework_final" to (errorCode == null),
                    "partial_discarded" to (errorCode != null),
                    "finality" to if (errorCode == null) {
                        "provider_final"
                    } else {
                        "provider_error"
                    },
                    "error_code" to errorCode,
                ),
            )
        }
    }
}
