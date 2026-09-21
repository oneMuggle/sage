package ai.arena.companion

import ai.arena.companion.account.AccountData
import ai.arena.companion.account.AccountReplacement
import ai.arena.companion.account.AccountVault
import ai.arena.companion.account.LoginTaskStart
import ai.arena.companion.account.ReplacementOutcome
import ai.arena.companion.account.SecretCipher
import java.io.File
import java.nio.file.Files
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class AccountReplacementTest {

    private object PrefixCipher : SecretCipher {
        private val prefix = "enc:".toByteArray(Charsets.UTF_8)

        override fun encrypt(plain: ByteArray): ByteArray = prefix + plain

        override fun decrypt(cipherText: ByteArray): ByteArray {
            require(cipherText.size >= prefix.size && prefix.indices.all { cipherText[it] == prefix[it] }) {
                "missing encrypted prefix"
            }
            return cipherText.copyOfRange(prefix.size, cipherText.size)
        }
    }

    private fun root(): File = Files.createTempDirectory("instances").toFile()

    private fun seed(root: File, name: String, account: AccountData): File {
        val dir = File(root, name).apply { mkdirs() }
        AccountVault(dir).save(account)
        File(dir, "task-settings.json").writeText("""{"prompt":"1+1="}""")
        return dir
    }

    // ---- LoginTaskStart ----------------------------------------------------

    @Test
    fun `login task start fires exactly once and only when complete`() {
        val flag = LoginTaskStart(true)
        assertFalse(flag.take(loginRunning = true, phase = "complete"))
        assertFalse(flag.take(loginRunning = false, phase = "verifying"))
        assertTrue(flag.pending)
        assertTrue(flag.take(loginRunning = false, phase = "complete"))
        // 已消费 → 再也不会触发，界面定时器重入也不行
        assertFalse(flag.take(loginRunning = false, phase = "complete"))
        assertFalse(flag.pending)
    }

    @Test
    fun `cancel clears a pending start`() {
        val flag = LoginTaskStart(true)
        flag.cancel()
        assertFalse(flag.take(loginRunning = false, phase = "complete"))
    }

    // ---- 换号 --------------------------------------------------------------

    @Test
    fun `derive name avoids collisions and does not stack suffixes`() {
        val root = root()
        val r = AccountReplacement(root)
        assertEquals("甲-2", r.deriveName("甲"))
        File(root, "甲-2").mkdirs()
        assertEquals("甲-3", r.deriveName("甲"))
        // 已经是派生名的不再层层叠加
        assertEquals("甲-3", r.deriveName("甲-2"))
    }

    @Test
    fun `successful replacement carries credentials and excludes the old mailbox`() {
        val root = root()
        seed(root, "甲", AccountData(email = "old@x.com", password = "Abcdefg!", name = "小明",
            verified = true, excludedEmails = listOf("older@x.com")))
        var activated: String? = null
        val outcome = AccountReplacement(root).replace("甲", {}) { activated = it }

        val done = outcome as ReplacementOutcome.Done
        assertEquals("甲-2", done.newInstance)
        assertEquals("甲-2", activated)

        val fresh = AccountVault(done.directory).load()
        assertEquals("Abcdefg!", fresh.password)     // 密码沿用
        assertEquals("小明", fresh.name)              // 昵称沿用
        assertEquals("", fresh.email)                 // 邮箱不继承
        assertFalse(fresh.verified)                   // 已验证状态不继承
        assertEquals("old@x.com", fresh.mailboxBeforeRefresh)
        assertTrue(fresh.mailboxRefreshRequested)
        assertFalse(fresh.mailboxChangeConfirmed)
        assertEquals(listOf("older@x.com", "old@x.com"), fresh.excludedEmails)
        // 任务设置跟着走
        assertTrue(File(done.directory, "task-settings.json").isFile)
    }

    @Test
    fun `the old instance is left completely untouched`() {
        val root = root()
        val old = seed(root, "甲", AccountData(email = "old@x.com", password = "Abcdefg!"))
        val before = File(old, "account.vault").readBytes()
        AccountReplacement(root).replace("甲", {}) {}
        assertTrue(before.contentEquals(File(old, "account.vault").readBytes()))
        assertEquals("old@x.com", AccountVault(old).load().email)
    }

    @Test
    fun `replacement uses injected vault factory for encrypted account vaults`() {
        val root = root()
        val old = File(root, "甲").apply { mkdirs() }
        AccountVault(old, PrefixCipher).save(AccountData(email = "old@x.com", password = "Abcdefg!", name = "小明"))

        val outcome = AccountReplacement(root) { dir -> AccountVault(dir, PrefixCipher) }
            .replace("甲", {}) {}

        val done = outcome as ReplacementOutcome.Done
        val fresh = AccountVault(done.directory, PrefixCipher).load()
        assertEquals("Abcdefg!", fresh.password)
        assertEquals("小明", fresh.name)
        assertEquals("old@x.com", fresh.mailboxBeforeRefresh)
        assertTrue(File(done.directory, "account.vault").readBytes().take(4).toByteArray()
            .contentEquals("enc:".toByteArray(Charsets.UTF_8)))
    }

    @Test
    fun `a failing pause aborts before any new instance is created`() {
        val root = root()
        seed(root, "甲", AccountData(password = "Abcdefg!"))
        val outcome = AccountReplacement(root)
            .replace("甲", { throw IllegalStateException("任务无法暂停") }) {}
        assertTrue(outcome is ReplacementOutcome.Failed)
        assertTrue((outcome as ReplacementOutcome.Failed).reason.contains("旧实例未改动"))
        assertFalse(File(root, "甲-2").exists())
    }

    @Test
    fun `a failing activation rolls the new instance back`() {
        val root = root()
        seed(root, "甲", AccountData(password = "Abcdefg!"))
        val outcome = AccountReplacement(root)
            .replace("甲", {}) { throw IllegalStateException("切换失败") }
        assertTrue(outcome is ReplacementOutcome.Failed)
        assertTrue((outcome as ReplacementOutcome.Failed).reason.contains("旧实例已保留"))
        assertFalse(File(root, "甲-2").exists())      // 半成品已清理
        assertTrue(File(root, "甲").isDirectory)
    }

    @Test
    fun `a missing instance is rejected`() {
        val outcome = AccountReplacement(root()).replace("不存在", {}) {}
        assertTrue(outcome is ReplacementOutcome.Failed)
    }
}
