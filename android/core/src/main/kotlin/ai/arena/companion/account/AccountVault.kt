// ref: reference/Arena模型助手-源码-fyb-0.1.0/src/AccountStore.cs
// ref: reference/Arena模型助手-源码-fyb-0.1.0/src/AccountData.cs
// spec: docs/mcp-android-implementation-plan.md §5「KeystoreVault.kt 对 AccountStore.cs」
//       §10 阶段 A「Keystore 解不开时报可恢复错误且**不覆盖**」
package ai.arena.companion.account

import java.io.File
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

/** ref: AccountData.cs —— 字段逐个对齐，含换号流程的三个标志位。 */
@Serializable
data class AccountData(
    val email: String = "",
    val password: String = "",
    val name: String = "",
    val verified: Boolean = false,
    val mailboxBeforeRefresh: String = "",
    val mailboxRefreshRequested: Boolean = false,
    val mailboxChangeConfirmed: Boolean = false,
    val excludedEmails: List<String> = emptyList(),
) {
    /** 日志/界面用，**永不输出密码**。 */
    fun redacted(): Map<String, Any> = mapOf(
        "email" to email,
        "name" to name,
        "verified" to verified,
        "hasPassword" to password.isNotEmpty(),
        "excludedEmails" to excludedEmails.size,
    )

    companion object {
        /** ref: AccountData.cs:L5-L12 —— 文案逐字沿用。 */
        fun nicknameError(name: String?): String {
            if (name.isNullOrBlank()) return "请填写注册昵称"
            if (name.trim().length > 40) return "昵称最多 40 个字符"
            if (name.any { it.isISOControl() }) return "昵称不能包含换行或控制字符"
            return ""
        }
    }
}

/**
 * 加解密后端。`:core` 保持纯 JVM 可测；`:app` 用 Android Keystore 实现它。
 *
 * 约定：`decrypt` 在**密钥不可用 / 密文损坏**时抛 [VaultUnavailableException]，
 * 调用方据此报可恢复错误，**绝不覆盖已有密文**。
 */
interface SecretCipher {
    fun encrypt(plain: ByteArray): ByteArray
    fun decrypt(cipherText: ByteArray): ByteArray
}

/** 保险库打不开（密钥被清除、设备换机、密文损坏）。**可恢复：让用户重新设置，而不是静默重置**。 */
class VaultUnavailableException(message: String, cause: Throwable? = null) :
    RuntimeException(message, cause)

/** 仅用于测试与不加密降级路径的直通实现。生产必须用 Keystore 实现。 */
object PlainTextCipher : SecretCipher {
    override fun encrypt(plain: ByteArray) = plain
    override fun decrypt(cipherText: ByteArray) = cipherText
}

/**
 * 账号保险库。对 `AccountStore`：DPAPI → [SecretCipher]（安卓侧为 Keystore）。
 *
 * 与 C# 的两处**有意差异**：
 * 1. C# 的 `EnsurePassword` 会从随软件分发的 `assets/account-defaults` 里读一个内置密码。
 *    安卓版不做这件事——内置共享密码在移动分发下等于把密码公开。改为 [needsSetup]，
 *    由 UI 引导用户自设（对应 `PasswordSetupDialog`）。
 * 2. 解密失败**不**返回空对象。C# 的 DPAPI 失败会直接抛；这里显式抛
 *    [VaultUnavailableException]，并且 [load] 失败后任何 [save] 都会被拒绝，
 *    避免用一份空账号覆盖掉其实只是暂时解不开的密文。
 */
class AccountVault(
    directory: File,
    private val cipher: SecretCipher = PlainTextCipher,
) {
    private val file = File(directory, "account.vault")
    private val json = Json { ignoreUnknownKeys = true }

    /** 上一次 load 是否遇到解不开的密文。为 true 时禁止写入。 */
    var locked: Boolean = false
        private set

    fun exists(): Boolean = file.exists()

    /** ref: AccountStore.cs:L18-L29。文件不存在 → 空账号（`Name=""`）。 */
    fun load(): AccountData {
        if (!file.exists()) { locked = false; return AccountData() }
        val plain = try {
            cipher.decrypt(file.readBytes())
        } catch (e: VaultUnavailableException) {
            locked = true; throw e
        } catch (e: Exception) {
            locked = true
            throw VaultUnavailableException("账号保险库无法解开，请重新设置昵称和密码（原数据已保留）。", e)
        }
        return try {
            json.decodeFromString(AccountData.serializer(), plain.toString(Charsets.UTF_8))
                .also { locked = false }
        } catch (e: Exception) {
            locked = true
            throw VaultUnavailableException("账号保险库内容已损坏，请重新设置昵称和密码（原数据已保留）。", e)
        }
    }

    /** ref: AccountStore.cs:L46-L59 —— tmp + 原子替换。 */
    fun save(account: AccountData) {
        if (locked) throw VaultUnavailableException(
            "保险库当前处于锁定状态，为避免覆盖既有账号数据，已拒绝写入。请先成功读取或显式重置。")
        val bytes = cipher.encrypt(
            json.encodeToString(AccountData.serializer(), account).toByteArray(Charsets.UTF_8))
        file.parentFile?.mkdirs()
        val tmp = File(file.parentFile, file.name + ".tmp")
        tmp.writeBytes(bytes)
        if (!tmp.renameTo(file)) {
            if (!(file.exists() && file.delete() && tmp.renameTo(file))) {
                tmp.delete()
                throw java.io.IOException("原子替换失败：${file.path}")
            }
        }
    }

    /** 是否还没设置过密码——取代 C# 的 `EnsurePassword` 内置默认密码路径。 */
    fun needsSetup(): Boolean = !file.exists() || load().password.isEmpty()

    /**
     * 用户确认"丢弃旧数据重来"后才允许调用。这是**唯一**能解除锁定的入口，
     * 必须由明确的用户动作触发，不能在任何自动路径里调。
     */
    fun resetAfterUserConfirmation(account: AccountData) {
        locked = false
        save(account)
    }

    /**
     * 对应 `PasswordSetupDialog.SavePassword` 的校验顺序（ref: L152-L164）：
     * 昵称 → 留空保留旧密码 → 密码强度 → 两次一致。返回错误文案，空串表示通过。
     */
    fun validateSetup(nickname: String?, password: String, confirmation: String,
                      hasSavedPassword: Boolean): String {
        val nameError = AccountData.nicknameError(nickname)
        if (nameError.isNotEmpty()) return nameError
        val keep = hasSavedPassword && password.isEmpty() && confirmation.isEmpty()
        if (keep) return ""
        val pwError = VaultPasswordPolicy.error(password)
        if (pwError.isNotEmpty()) return pwError
        if (password != confirmation) return "两次输入的密码不一致"
        return ""
    }

    /** 配套 [validateSetup]：留空即保留旧密码（ref: L156/L162 的 keepPassword 语义）。 */
    fun applySetup(current: AccountData, nickname: String, password: String,
                   hasSavedPassword: Boolean): AccountData {
        val keep = hasSavedPassword && password.isEmpty()
        return current.copy(
            name = nickname.trim(),
            password = if (keep) current.password else password,
        )
    }
}
