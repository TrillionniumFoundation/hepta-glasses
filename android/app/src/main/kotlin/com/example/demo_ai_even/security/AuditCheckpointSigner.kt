package com.example.demo_ai_even.security

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import java.security.KeyStore
import javax.crypto.KeyGenerator
import javax.crypto.Mac
import javax.crypto.SecretKey

object AuditCheckpointSigner {
    private const val KEYSTORE = "AndroidKeyStore"
    private const val KEY_ALIAS = "hepta_glasses_audit_checkpoint_hmac_v1"
    private const val ALGORITHM = "HmacSHA256"

    @Synchronized
    fun authenticate(payload: ByteArray): ByteArray {
        require(payload.isNotEmpty()) { "Audit checkpoint payload is empty" }
        val mac = Mac.getInstance(ALGORITHM)
        mac.init(loadOrCreateKey())
        return mac.doFinal(payload)
    }

    private fun loadOrCreateKey(): SecretKey {
        val keyStore = KeyStore.getInstance(KEYSTORE).apply { load(null) }
        val existing = keyStore.getKey(KEY_ALIAS, null) as? SecretKey
        if (existing != null) return existing

        val generator = KeyGenerator.getInstance(
            KeyProperties.KEY_ALGORITHM_HMAC_SHA256,
            KEYSTORE,
        )
        generator.init(
            KeyGenParameterSpec.Builder(
                KEY_ALIAS,
                KeyProperties.PURPOSE_SIGN or KeyProperties.PURPOSE_VERIFY,
            )
                .setDigests(KeyProperties.DIGEST_SHA256)
                .setUserAuthenticationRequired(false)
                .build(),
        )
        return generator.generateKey()
    }
}
