// spec: docs/mcp-android-implementation-plan.md §5「KeystoreVault.kt（+ Android Keystore）」
//       §10 阶段 A「Keystore 解不开时报可恢复错误且不覆盖」
package ai.arena.companion.app

import ai.arena.companion.account.SecretCipher
import ai.arena.companion.account.VaultUnavailableException
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * Android Keystore 的 AES/GCM 实现，对应桌面端的 DPAPI `CurrentUser` 作用域。
 *
 * 密文格式：`[1 字节版本][12 字节 IV][GCM 密文]`。IV 每次随机生成并随密文存储——
 * GCM 下 **IV 复用会直接泄露明文**，所以绝不复用。
 *
 * 密钥**不**设 `setUserAuthenticationRequired`：后台自动化服务在锁屏状态下也要能读账号，
 * 要求用户认证会让前台任务在熄屏后直接失败。硬件绑定（不可导出）已经挡住了拷走文件离线解密。
 */
class KeystoreCipher(private val alias: String = DEFAULT_ALIAS) : SecretCipher {

    override fun encrypt(plain: ByteArray): ByteArray {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, loadOrCreateKey())
        val body = cipher.doFinal(plain)
        val iv = cipher.iv
        require(iv.size == IV_BYTES) { "意外的 GCM IV 长度：${iv.size}" }
        return ByteArray(1 + IV_BYTES + body.size).also {
            it[0] = VERSION
            System.arraycopy(iv, 0, it, 1, IV_BYTES)
            System.arraycopy(body, 0, it, 1 + IV_BYTES, body.size)
        }
    }

    override fun decrypt(cipherText: ByteArray): ByteArray {
        if (cipherText.size <= 1 + IV_BYTES || cipherText[0] != VERSION) {
            throw VaultUnavailableException("账号保险库格式无法识别，请重新设置昵称和密码（原数据已保留）。")
        }
        val key = existingKey()
            // 密钥没了（清除凭据 / 换机 / 恢复出厂）——这是**可恢复**错误，
            // 上层必须提示重设而不是拿空账号覆盖密文。
            ?: throw VaultUnavailableException("设备密钥已失效，账号需要重新设置（原数据已保留）。")
        return try {
            Cipher.getInstance(TRANSFORMATION).run {
                init(Cipher.DECRYPT_MODE, key,
                    GCMParameterSpec(TAG_BITS, cipherText, 1, IV_BYTES))
                doFinal(cipherText, 1 + IV_BYTES, cipherText.size - 1 - IV_BYTES)
            }
        } catch (e: Exception) {
            throw VaultUnavailableException("账号保险库无法解开，请重新设置昵称和密码（原数据已保留）。", e)
        }
    }

    private fun keyStore(): KeyStore =
        KeyStore.getInstance(PROVIDER).apply { load(null) }

    private fun existingKey(): SecretKey? = try {
        keyStore().getKey(alias, null) as? SecretKey
    } catch (_: Exception) {
        null
    }

    private fun loadOrCreateKey(): SecretKey = existingKey() ?: try {
        KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, PROVIDER).apply {
            init(
                KeyGenParameterSpec.Builder(
                    alias,
                    KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
                )
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .setKeySize(256)
                    .build()
            )
        }.generateKey()
    } catch (e: Exception) {
        throw VaultUnavailableException("无法创建设备密钥，账号无法加密保存。", e)
    }

    companion object {
        const val DEFAULT_ALIAS = "ai.arena.companion.account"
        private const val PROVIDER = "AndroidKeyStore"
        private const val TRANSFORMATION = "AES/GCM/NoPadding"
        private const val IV_BYTES = 12
        private const val TAG_BITS = 128
        private const val VERSION: Byte = 1
    }
}
