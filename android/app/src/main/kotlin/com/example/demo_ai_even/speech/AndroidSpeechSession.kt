package com.example.demo_ai_even.speech

import android.os.Handler
import android.os.Looper
import com.example.demo_ai_even.bluetooth.BleChannelHelper
import java.util.concurrent.Executors

/**
 * Process-local custody for one Android speech session.
 *
 * The session is bound to the exact assistant generation and G1 pair identity
 * carried by the short-lived speech ticket. It never persists audio, tokens or
 * transcripts. Final provider work is serialized off the Flutter/GATT threads,
 * and a later start/cancel fences an older result before EventChannel delivery.
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
    private var generation: Int = 0
    private var pairIdentity: String = ""
    private var epoch: Long = 0
    private var finalizing: Boolean = false

    fun start(ticket: SpeechTicket) {
        val next = AndroidPcmAsr(ticket)
        synchronized(lock) {
            recognizer?.cancel()
            epoch += 1
            recognizer = next
            generation = ticket.generation
            pairIdentity = ticket.pairIdentity
            finalizing = false
        }
    }

    fun append(
        pcm: ByteArray,
        expectedGeneration: Int,
        expectedPairIdentity: String,
    ) {
        val active = synchronized(lock) {
            if (finalizing ||
                expectedGeneration != generation ||
                expectedPairIdentity != pairIdentity
            ) {
                null
            } else {
                recognizer
            }
        } ?: return

        try {
            active.append(pcm, expectedGeneration, expectedPairIdentity)
        } catch (_: IllegalArgumentException) {
            abort(
                expectedGeneration,
                expectedPairIdentity,
                "SpeechPcmInvalid",
            )
        } catch (_: IllegalStateException) {
            abort(
                expectedGeneration,
                expectedPairIdentity,
                "SpeechSessionInvalid",
            )
        }
    }

    fun stop(
        expectedGeneration: Int,
        expectedPairIdentity: String,
        finalize: Boolean,
    ): Boolean {
        if (!finalize) {
            return cancel(expectedGeneration, expectedPairIdentity)
        }

        val captured: Pair<AndroidPcmAsr, Long> = synchronized(lock) {
            val active = recognizer
            if (active == null ||
                finalizing ||
                expectedGeneration != generation ||
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
                    expectedGeneration,
                    expectedPairIdentity,
                )
                completeIfCurrent(
                    captured.second,
                    expectedGeneration,
                    expectedPairIdentity,
                    transcript,
                    null,
                )
            } catch (error: Exception) {
                completeIfCurrent(
                    captured.second,
                    expectedGeneration,
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
        expectedGeneration: Int,
        expectedPairIdentity: String,
    ): Boolean = synchronized(lock) {
        val active = recognizer
        if (active == null ||
            expectedGeneration != generation ||
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
        expectedGeneration: Int,
        expectedPairIdentity: String,
        code: String,
    ) {
        val shouldEmit = synchronized(lock) {
            if (expectedGeneration != generation ||
                expectedPairIdentity != pairIdentity
            ) {
                false
            } else {
                epoch += 1
                recognizer?.cancel()
                clearLocked()
                true
            }
        }
        if (shouldEmit) {
            emitFinal(expectedGeneration, "", code)
        }
    }

    private fun completeIfCurrent(
        capturedEpoch: Long,
        expectedGeneration: Int,
        expectedPairIdentity: String,
        transcript: String,
        errorCode: String?,
    ) {
        val shouldEmit = synchronized(lock) {
            if (capturedEpoch != epoch ||
                expectedGeneration != generation ||
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
            emitFinal(expectedGeneration, transcript.trim(), errorCode)
        }
    }

    private fun clearLocked() {
        recognizer = null
        generation = 0
        pairIdentity = ""
        finalizing = false
    }

    private fun emitFinal(
        completedGeneration: Int,
        transcript: String,
        errorCode: String?,
    ) {
        mainHandler.post {
            BleChannelHelper.bleSpeechRecognize(
                mapOf(
                    "script" to transcript,
                    "generation" to completedGeneration,
                    "is_final" to true,
                    "is_framework_final" to (errorCode == null),
                    "partial_discarded" to false,
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
