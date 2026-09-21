package ai.arena.companion

import ai.arena.companion.account.AccountData
import ai.arena.companion.account.AccountVault
import ai.arena.companion.account.SecretCipher
import ai.arena.companion.account.VaultPasswordPolicy
import ai.arena.companion.account.VaultUnavailableException
import java.io.File
import java.nio.file.Files
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/** 可切换成"打不开"的假密钥后端，模拟 Keystore 密钥被清除。 */
private class FlakyCipher(var broken: Boolean = false) : SecretCipher {
    override fun encrypt(plain: ByteArray) = plain.map { (it.toInt() xor 0x5A).toByte() }.toByteArray()
    override fun decrypt(cipherText: ByteArray): ByteArray {
        if (broken) throw VaultUnavailableException("密钥不可用")
        return cipherText.map { (it.toInt() xor 0x5A).toByte() }.toByteArray()
    }
}

class AccountVaultTest {

    private fun dir(): File = Files.createTempDirectory("vault").toFile()

    @Test
    fun `vault password policy matches the desktop rules verbatim`() {
        assertEquals("密码至少需要 8 个字符", VaultPasswordPolicy.error(""))
        assertEquals("密码至少需要 8 个字符", VaultPasswordPolicy.error("Ab!45"))
        assertEquals("密码至少需要一个大写字母", VaultPasswordPolicy.error("abcdefg!"))
        assertEquals("密码至少需要一个符号", VaultPasswordPolicy.error("Abcdefgh"))
        assertEquals("", VaultPasswordPolicy.error("Abcdefg!"))
        assertTrue(VaultPasswordPolicy.isValid("Abcdefg!"))
        // 非 ASCII 符号也算符号
        assertEquals("", VaultPasswordPolicy.error("Abcdefg，"))
    }

    @Test
    fun `nickname validation matches the desktop rules verbatim`() {
        assertEquals("请填写注册昵称", AccountData.nicknameError("   "))
        assertEquals("昵称最多 40 个字符", AccountData.nicknameError("x".repeat(41)))
        assertEquals("昵称不能包含换行或控制字符", AccountData.nicknameError("ab\ncd"))
        assertEquals("", AccountData.nicknameError(" 小明 "))
    }

    @Test
    fun `missing file yields an empty account and round trip works`() {
        val d = dir()
        val vault = AccountVault(d, FlakyCipher())
        assertEquals(AccountData(), vault.load())
        assertTrue(vault.needsSetup())

        val account = AccountData(email = "a@b.c", password = "Abcdefg!", name = "小明", verified = true)
        vault.save(account)
        assertEquals(account, AccountVault(d, FlakyCipher()).load())
        assertFalse(AccountVault(d, FlakyCipher()).needsSetup())
    }

    @Test
    fun `stored bytes are not plaintext`() {
        val d = dir()
        AccountVault(d, FlakyCipher()).save(AccountData(password = "Abcdefg!"))
        val raw = File(d, "account.vault").readText(Charsets.ISO_8859_1)
        assertFalse(raw.contains("Abcdefg!"))
    }

    @Test
    fun `undecryptable vault raises a recoverable error and never overwrites`() {
        val d = dir()
        val good = FlakyCipher()
        val vault = AccountVault(d, good)
        vault.save(AccountData(email = "keep@me", password = "Abcdefg!"))
        val before = File(d, "account.vault").readBytes()

        good.broken = true
        assertFailsWith<VaultUnavailableException> { vault.load() }
        assertTrue(vault.locked)
        // 锁定后写入被拒绝 —— 旧密文一字节未动
        assertFailsWith<VaultUnavailableException> { vault.save(AccountData()) }
        assertTrue(before.contentEquals(File(d, "account.vault").readBytes()))

        // 密钥恢复后能正常读回，锁定解除
        good.broken = false
        assertEquals("keep@me", vault.load().email)
        assertFalse(vault.locked)
    }

    @Test
    fun `corrupt payload is reported as recoverable rather than silently reset`() {
        val d = dir()
        File(d, "account.vault").writeBytes(byteArrayOf(1, 2, 3, 4))
        val vault = AccountVault(d, FlakyCipher())
        val e = assertFailsWith<VaultUnavailableException> { vault.load() }
        assertTrue(e.message!!.contains("原数据已保留"))
        assertTrue(vault.locked)
    }

    @Test
    fun `explicit user confirmed reset is the only way out of a lock`() {
        val d = dir()
        File(d, "account.vault").writeBytes(byteArrayOf(9))
        val vault = AccountVault(d, FlakyCipher())
        assertFailsWith<VaultUnavailableException> { vault.load() }
        vault.resetAfterUserConfirmation(AccountData(name = "新号", password = "Abcdefg!"))
        assertFalse(vault.locked)
        assertEquals("新号", vault.load().name)
    }

    @Test
    fun `setup validation follows the dialog order`() {
        val vault = AccountVault(dir(), FlakyCipher())
        assertEquals("请填写注册昵称", vault.validateSetup("", "Abcdefg!", "Abcdefg!", false))
        // 已有密码 + 两栏留空 → 保留
        assertEquals("", vault.validateSetup("小明", "", "", true))
        // 没有旧密码 + 留空 → 走强度校验
        assertEquals("密码至少需要 8 个字符", vault.validateSetup("小明", "", "", false))
        assertEquals("两次输入的密码不一致", vault.validateSetup("小明", "Abcdefg!", "Abcdefg?", false))
        assertEquals("", vault.validateSetup("小明", "Abcdefg!", "Abcdefg!", false))
    }

    @Test
    fun `applySetup keeps the old password when left blank`() {
        val vault = AccountVault(dir(), FlakyCipher())
        val current = AccountData(name = "旧", password = "OldPass!")
        assertEquals("OldPass!", vault.applySetup(current, " 新 ", "", true).password)
        assertEquals("新", vault.applySetup(current, " 新 ", "", true).name)
        assertEquals("NewPass!", vault.applySetup(current, "新", "NewPass!", true).password)
    }

    @Test
    fun `redacted output never contains the password`() {
        val r = AccountData(email = "a@b.c", password = "Abcdefg!", name = "n").redacted()
        assertFalse(r.values.any { it.toString().contains("Abcdefg!") })
        assertEquals(true, r["hasPassword"])
    }
}
