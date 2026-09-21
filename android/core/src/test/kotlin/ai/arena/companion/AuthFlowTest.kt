package ai.arena.companion

import ai.arena.companion.account.AccountData
import ai.arena.companion.account.AccountVault
import ai.arena.companion.account.AuthFlow
import ai.arena.companion.account.AuthPages
import java.io.File
import java.nio.file.Files
import java.time.Instant
import java.util.ArrayDeque
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.async
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest

private class FakeAuthPages : AuthPages {
    var arenaStage: String = "loading"
    var authStage: String = "loading"
    var account: String = ""
    var mailbox: String = ""
    var blocker: String = ""
    val navigations = mutableListOf<Pair<String, String>>()
    val actions = mutableListOf<Pair<String, String>>()

    override suspend fun read(target: String): Map<String, Any?> = when (target) {
        "auth" -> mapOf(
            "stage" to authStage,
            "mailbox" to mailbox,
            "canConfirmMailboxChange" to false,
            "blocker" to blocker,
        )
        else -> mapOf(
            "stage" to arenaStage,
            "account" to account,
            "blocker" to blocker,
        )
    }

    override suspend fun act(target: String, action: String, data: AccountData) {
        actions += target to action
        when (action) {
            "openLogin" -> arenaStage = "email"
            "email" -> assertEquals(data.email, "saved@example.com")
            "submitEmail" -> arenaStage = "loginPassword"
            "password" -> Unit
            "submitPassword" -> {
                arenaStage = "authenticated"
                account = data.email
            }
            else -> Unit
        }
    }

    override fun navigate(target: String, url: String) {
        navigations += target to url
    }
}

private class QueuedAuthPages : AuthPages {
    private val reads = linkedMapOf<String, ArrayDeque<Map<String, Any?>>>()
    val navigations = mutableListOf<Pair<String, String>>()
    val actions = mutableListOf<Pair<String, String>>()

    fun enqueue(target: String, vararg states: Map<String, Any?>) {
        val queue = reads.getOrPut(target) { ArrayDeque() }
        states.forEach(queue::add)
    }

    override suspend fun read(target: String): Map<String, Any?> {
        val queue = reads[target]
        check(queue != null && queue.isNotEmpty()) { "没有为 $target 准备读取状态" }
        return queue.removeFirst()
    }

    override suspend fun act(target: String, action: String, data: AccountData) {
        actions += target to action
    }

    override fun navigate(target: String, url: String) {
        navigations += target to url
    }
}

private fun authState(
    stage: String,
    mailbox: String = "",
    mailAvailable: Boolean = false,
    verifyUrl: String = "",
    blocker: String = "",
    account: String = "",
    canConfirmMailboxChange: Boolean = false,
): Map<String, Any?> = mapOf(
    "stage" to stage,
    "mailbox" to mailbox,
    "mailAvailable" to mailAvailable,
    "verifyUrl" to verifyUrl,
    "blocker" to blocker,
    "account" to account,
    "canConfirmMailboxChange" to canConfirmMailboxChange,
)

class AuthFlowTest {
    private fun dir(): File = Files.createTempDirectory("auth-flow").toFile()

    @Test
    fun `already authenticated page completes and stores verified account`() = runTest {
        val d = dir()
        val vault = AccountVault(d)
        vault.save(AccountData(email = "saved@example.com", password = "Abcdefg!", name = "小明"))
        val pages = FakeAuthPages().apply {
            arenaStage = "authenticated"
            account = "saved@example.com"
        }
        var now = Instant.parse("2026-09-20T00:00:00Z")
        val flow = AuthFlow(pages, vault, clock = { now }, loginDelay = { now = now.plusMillis(it) })

        flow.start()
        flow.tick()

        assertFalse(flow.running)
        assertEquals("complete", flow.phase)
        assertEquals("saved@example.com", flow.email)
        assertTrue(vault.load().verified)
        assertEquals("https://arena.ai/agent", pages.navigations.first().second)
        assertEquals("about:blank", pages.navigations.last().second)
    }

    @Test
    fun `saved account logs in through email and password without duplicate submissions`() = runTest {
        val vault = AccountVault(dir()).apply {
            save(AccountData(email = "saved@example.com", password = "Abcdefg!", name = "小明", verified = true))
        }
        val pages = FakeAuthPages().apply { arenaStage = "loggedOut" }
        var now = Instant.parse("2026-09-20T00:00:00Z")
        val flow = AuthFlow(pages, vault, clock = { now }, loginDelay = { now = now.plusMillis(it) })

        flow.start()
        repeat(6) { flow.tick() }

        assertEquals("complete", flow.phase)
        assertFalse(flow.running)
        assertEquals(
            listOf(
                "arena" to "openLogin",
                "arena" to "email",
                "arena" to "submitEmail",
                "arena" to "password",
                "arena" to "submitPassword",
            ),
            pages.actions,
        )
    }

    @Test
    fun `verification blocker pauses and then resumes original phase`() = runTest {
        val vault = AccountVault(dir()).apply {
            save(AccountData(email = "saved@example.com", password = "Abcdefg!", name = "小明", verified = true))
        }
        val pages = FakeAuthPages().apply {
            arenaStage = "email"
            blocker = "需要亲自完成人机验证"
        }
        var now = Instant.parse("2026-09-20T00:00:00Z")
        val flow = AuthFlow(pages, vault, clock = { now }, loginDelay = { now = now.plusMillis(it) })

        flow.start()
        flow.tick()
        assertFalse(flow.running)
        assertTrue(flow.waitingForVerification)
        assertEquals("verification", flow.phase)

        pages.blocker = ""
        flow.tick()
        assertTrue(flow.running)
        assertFalse(flow.waitingForVerification)
        assertEquals("inspect", flow.phase)
        assertTrue(flow.message.contains("自动继续登录"))
    }

    @Test
    fun `unfinished registration refuses to submit when mailbox does not match saved email`() = runTest {
        val vault = AccountVault(dir()).apply {
            save(AccountData(email = "old@example.com", password = "Abcdefg!", name = "小明", verified = false))
        }
        val pages = FakeAuthPages().apply {
            arenaStage = "email"
            authStage = "mail"
            mailbox = "other@example.com"
        }
        var now = Instant.parse("2026-09-20T00:00:00Z")
        val flow = AuthFlow(pages, vault, clock = { now }, loginDelay = { now = now.plusMillis(it) })

        flow.start()
        flow.tick()

        assertEquals("paused", flow.phase)
        assertTrue(flow.message.contains("旧实例已保留") || flow.message.contains("账号未改变"))
        assertTrue(pages.actions.isEmpty())
    }

    @Test
    fun `existing inbox is not reloaded and visible confirmation mail is opened`() = runTest {
        val vault = AccountVault(dir()).apply {
            save(AccountData(email = "expected@example.test", password = "Abcdefg!", name = "小明", verified = false))
        }
        val pages = QueuedAuthPages().apply {
            enqueue("arena", authState("verification"))
            enqueue(
                "auth",
                authState("mail", mailbox = "changed@example.test", mailAvailable = true),
                authState("mail", mailbox = "changed@example.test", mailAvailable = true),
                authState(
                    "mail",
                    mailbox = "changed@example.test",
                    verifyUrl = "https://arena.ai/nextjs-api/callback/email?token=test",
                ),
            )
        }
        var now = Instant.parse("2026-09-20T00:00:00Z")
        val flow = AuthFlow(pages, vault, clock = { now }, loginDelay = { now = now.plusMillis(it) })

        flow.start()
        flow.tick()
        assertEquals("mail", flow.phase)
        assertFalse(pages.navigations.any { it.first == "auth" && it.second.contains("10minutemail.one") })

        flow.tick()
        assertTrue("auth" to "openMail" in pages.actions)
        assertTrue(flow.running)

        flow.tick()
        assertEquals("verify", flow.phase)
        assertTrue(pages.navigations.any {
            it.first == "auth" && it.second.startsWith("https://arena.ai/nextjs-api/callback/email")
        })
    }

    @Test
    fun `missing auth mailbox page is restored before continuing registration`() = runTest {
        val vault = AccountVault(dir()).apply {
            save(AccountData(email = "expected@example.test", password = "Abcdefg!", name = "小明", verified = false))
        }
        val pages = QueuedAuthPages().apply {
            enqueue("arena", authState("verification"))
            enqueue("auth", authState("loading"))
        }
        var now = Instant.parse("2026-09-20T00:00:00Z")
        val flow = AuthFlow(pages, vault, clock = { now }, loginDelay = { now = now.plusMillis(it) })

        flow.start()
        flow.tick()

        assertTrue("auth" to "https://10minutemail.one/zh" in pages.navigations)
        assertTrue(flow.running)
        assertEquals("mail", flow.phase)
    }

    @Test
    @OptIn(ExperimentalCoroutinesApi::class)
    fun `stop during delayed login action cancels pending click and keeps stop reason`() = runTest {
        val vault = AccountVault(dir()).apply {
            save(AccountData(email = "saved@example.com", password = "Abcdefg!", name = "小明", verified = true))
        }
        val pages = FakeAuthPages().apply { arenaStage = "email" }
        val gate = CompletableDeferred<Unit>()
        val flow = AuthFlow(pages, vault, loginDelay = { gate.await() })

        flow.start()
        val pending = async { flow.tick() }
        runCurrent()
        assertTrue(flow.isBusy)
        assertTrue(pages.actions.isEmpty())

        flow.stop("user stopped")
        gate.complete(Unit)
        pending.await()

        assertTrue(pages.actions.isEmpty())
        assertFalse(flow.running)
        assertEquals("user stopped", flow.message)
    }
}
