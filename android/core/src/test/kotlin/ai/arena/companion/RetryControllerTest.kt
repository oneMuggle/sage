package ai.arena.companion

import ai.arena.companion.automation.ArenaPage
import ai.arena.companion.automation.PageReadTimeoutException
import ai.arena.companion.automation.PageState
import ai.arena.companion.automation.ProbeReader
import ai.arena.companion.automation.ProbeSnapshot
import ai.arena.companion.automation.RequestPreparation
import ai.arena.companion.automation.RetryController
import java.time.Instant
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class RetryControllerTest {

    private class FakeClock(var now: Instant = Instant.parse("2026-09-20T00:00:00Z")) {
        fun advance(seconds: Long) { now = now.plusSeconds(seconds) }
    }

    private class FakePage(
        var state: PageState = PageState(url = "https://arena.ai/agent", main = true, editor = true, newLinks = 1),
    ) : ArenaPage {
        override val demo = false
        var failTimes = 0
        val acts = mutableListOf<String>()
        override suspend fun read(prompt: String?): PageState {
            if (failTimes > 0) { failTimes--; throw PageReadTimeoutException("busy") }
            return state.copy()
        }
        override suspend fun act(name: String, prompt: String?) { acts += name }
        /** 路由放行开关：默认放行；个别用例切 false 模拟停在非 /agent 页面。 */
        var allowed = true
        override fun isAllowed(url: String?) = allowed
    }

    private class FakeProbe(var snapshot: ProbeSnapshot? = null) : ProbeReader {
        override suspend fun read(): ProbeSnapshot? = snapshot
    }

    private fun controller(
        page: FakePage,
        clock: FakeClock,
        probe: FakeProbe = FakeProbe(),
        preparation: RequestPreparation? = null,
    ) = RetryController(page, probe, null, { clock.now }, preparation)

    /** 对 IRequestPreparation 的最小假件：required / ready 可控，记录 prepare / check / beginRound 次数。 */
    private class FakePreparation(override var required: Boolean = true) : RequestPreparation {
        var ready = false
        var prepares = 0; var checks = 0; var rounds = 0
        override fun beginRound() { rounds++ }
        override suspend fun prepare(): Boolean { prepares++; return ready }
        override suspend fun check(): Boolean { checks++; return ready }
    }

    /** 把阶段机推到 fill 已执行后的那一步：inspect → new → waitNew → fill。 */
    private suspend fun driveThroughFill(c: RetryController, page: FakePage) {
        c.tick()                                   // inspect -> new
        assertEquals("new", c.phase)
        c.tick()                                   // new -> waitNew（act new）
        assertEquals("waitNew", c.phase)
        page.state = page.state.copy(url = "https://arena.ai/agent", conversation = false, editor = true, draft = "")
        c.tick()                                   // waitNew -> fill
        assertEquals("fill", c.phase)
        c.tick()                                   // fill -> prepare / send
    }

    @Test
    fun `without attachments fill goes straight to send exactly like the desktop flow`() = runTest {
        val clock = FakeClock(); val page = FakePage()
        val prep = FakePreparation(required = false)
        val c = controller(page, clock, preparation = prep)
        c.start("1+1=", 1)
        driveThroughFill(c, page)
        assertEquals("send", c.phase)
        assertEquals(0, prep.prepares)
        assertEquals(2, prep.rounds)               // start() 与 new 阶段各触发一次 beginRound（对 C# L152 / Tick L114）
    }

    @Test
    fun `with attachments fill enters prepare, waits for readiness and never sends before it`() = runTest {
        val clock = FakeClock(); val page = FakePage()
        val prep = FakePreparation(required = true)
        val c = controller(page, clock, preparation = prep)
        c.start("1+1=", 1)
        driveThroughFill(c, page)
        assertEquals("prepare", c.phase)
        c.tick(); c.tick()
        assertEquals("prepare", c.phase)
        assertEquals(2, prep.prepares)
        assertTrue(page.acts.none { it == "send" })
        prep.ready = true
        c.tick()
        assertEquals("send", c.phase)
        page.state = page.state.copy(draft = "1+1=", sendReady = true)
        c.tick()
        assertEquals("confirm", c.phase)
        assertEquals(1, page.acts.count { it == "send" })
        assertTrue(prep.checks >= 1)               // send 前必经 check()
    }

    @Test
    fun `prepare phase pauses after 60 seconds without confirmation and does not send`() = runTest {
        val clock = FakeClock(); val page = FakePage()
        val prep = FakePreparation(required = true)
        val c = controller(page, clock, preparation = prep)
        c.start("1+1=", 1)
        driveThroughFill(c, page)
        assertEquals("prepare", c.phase)
        clock.advance(59); c.tick()
        assertTrue(c.running)
        clock.advance(2); c.tick()
        assertFalse(c.running)
        assertEquals("附件上传尚未确认，已暂停，不会无附件发送", c.message)
        assertTrue(page.acts.none { it == "send" })
    }

    @Test
    fun `send phase pauses when the attachment check fails at the last moment`() = runTest {
        val clock = FakeClock(); val page = FakePage()
        val prep = FakePreparation(required = true).apply { ready = true }
        val c = controller(page, clock, preparation = prep)
        c.start("1+1=", 1)
        driveThroughFill(c, page)
        c.tick()                                   // prepare -> send
        assertEquals("send", c.phase)
        prep.ready = false
        page.state = page.state.copy(draft = "1+1=", sendReady = true)
        c.tick()
        assertFalse(c.running)
        assertEquals("发送前附件发生改变，请检查后重新开始", c.message)
        assertTrue(page.acts.none { it == "send" })
    }

    @Test
    fun `stage failure inside prepare pauses with the readable reason`() = runTest {
        val clock = FakeClock(); val page = FakePage()
        val prep = object : RequestPreparation {
            override val required = true
            override fun beginRound() {}
            override suspend fun prepare(): Boolean = throw IllegalStateException("没有找到唯一可用的附件上传入口")
            override suspend fun check(): Boolean = false
        }
        val c = controller(page, clock, preparation = prep)
        c.start("1+1=", 1)
        driveThroughFill(c, page)
        assertEquals("prepare", c.phase)
        c.tick()
        assertFalse(c.running)
        assertEquals("操作已暂停：没有找到唯一可用的附件上传入口", c.message)
        assertTrue(page.acts.none { it == "send" })
    }

    @Test
    fun `title truncates model segment and keeps timestamp`() {
        val long = "m".repeat(200)
        val title = RetryController.buildTitle(long, Instant.parse("2026-09-20T01:02:00Z"))
        assertEquals(100, title.length)
        assertTrue(title.endsWith(" · " + title.takeLast(11)))
        assertTrue(RetryController.buildTitle("  ", Instant.now()).startsWith("未识别"))
    }

    @Test
    fun `inconsistent snapshot is ignored entirely`() = runTest {
        val clock = FakeClock(); val page = FakePage()
        val c = controller(page, clock)
        c.start("1+1=", 1)
        page.state = page.state.copy(snapshotConsistent = false, main = false)
        clock.advance(300)
        c.tick()
        // 不一致快照既不推进也不触发任何超时暂停
        assertEquals("inspect", c.phase)
        assertTrue(c.running)
    }

    @Test
    fun `terms modal is handled before visibility checks and only once`() = runTest {
        val clock = FakeClock(); val page = FakePage()
        val c = controller(page, clock)
        c.start("1+1=", 1)
        page.state = page.state.copy(termsPending = true, main = false)
        c.tick()
        assertEquals(listOf("terms"), page.acts)
        // 仍未关闭：不重复点击
        c.tick()
        assertEquals(listOf("terms"), page.acts)
        assertTrue(c.running)
        clock.advance(21)
        c.tick()
        assertFalse(c.running)
        assertTrue(c.message.contains("不会重复点击同意或重发消息"))
    }

    @Test
    fun `multiple new chat entries pause instead of guessing`() = runTest {
        val clock = FakeClock(); val page = FakePage()
        val c = controller(page, clock)
        c.start("1+1=", 1)
        c.tick()                       // inspect -> new
        assertEquals("new", c.phase)
        page.state = page.state.copy(newLinks = 2)
        c.tick()
        assertFalse(c.running)
        assertTrue(c.message.contains("多个 New Chat 入口"))
        assertTrue(page.acts.isEmpty())
    }

    @Test
    fun `sidebar expansion is attempted once then times out`() = runTest {
        val clock = FakeClock(); val page = FakePage()
        val c = controller(page, clock)
        c.start("1+1=", 1)
        c.tick()
        page.state = page.state.copy(newLinks = 0, canExpand = true)
        c.tick(); c.tick()
        assertEquals(listOf("expand"), page.acts)
        clock.advance(21)
        c.tick()
        assertFalse(c.running)
        assertTrue(c.message.contains("未能确认 New Chat 入口"))
    }

    @Test
    fun `captcha blocker waits for human and resumes without resending`() = runTest {
        val clock = FakeClock(); val page = FakePage()
        val c = controller(page, clock)
        c.start("1+1=", 1)
        page.state = page.state.copy(blocker = RetryController.BLOCKER_VERIFICATION)
        c.tick()
        assertFalse(c.running)
        assertTrue(c.waitingForVerification)
        page.state = page.state.copy(blocker = null)
        c.tick()
        assertTrue(c.running)
        assertFalse(c.waitingForVerification)
        assertTrue(page.acts.none { it == "send" })
    }

    @Test
    fun `read timeout backs off exponentially and pauses only after 120s`() = runTest {
        val clock = FakeClock(); val page = FakePage()
        val c = controller(page, clock)
        c.start("1+1=", 1)
        page.failTimes = 1
        c.tick()
        assertTrue(c.running)          // 单次失败不暂停
        clock.advance(130)
        page.failTimes = 1
        c.tick()
        assertFalse(c.running)
        assertTrue(c.message.contains("连续 2 分钟无法读取"))
    }

    @Test
    fun `epoch guard drops stale async results`() = runTest {
        val clock = FakeClock()
        val page = FakePage()
        val c = controller(page, clock)
        c.start("1+1=", 1)
        c.tick()
        val phaseBefore = c.phase
        c.pause("人工暂停")
        // 暂停后 tick 不得推进任何状态
        c.tick()
        assertEquals(phaseBefore, c.phase)
        assertFalse(c.running)
    }

    @Test
    fun `page outside the conversation route pauses with a readable reason`() = runTest {
        val clock = FakeClock(); val page = FakePage()
        val c = controller(page, clock)
        c.start("1+1=", 1)
        page.state = PageState(url = "https://arena.ai/", main = true, editor = true)
        page.allowed = false
        c.tick()               // 第一次观察到「不在对话页」，计时从这里开始
        assertEquals("inspect", c.phase)
        assertTrue(c.running)
        clock.advance(19)
        c.tick()
        assertTrue(c.running)  // 19 秒内只在等，不暂停
        clock.advance(2)
        c.tick()
        assertFalse(c.running)
        assertTrue(c.message.contains("arena.ai/agent"))
    }

    @Test
    fun `resume restarts the off-route stall timer`() = runTest {
        val clock = FakeClock(); val page = FakePage()
        val c = controller(page, clock)
        c.start("1+1=", 1)
        page.allowed = false
        c.tick()
        clock.advance(21)
        c.tick()
        assertFalse(c.running)  // 连续 21 秒不在对话页 → 暂停并给出原因
        c.resume()
        c.tick()                // 恢复后重新观察，计时从头开始
        clock.advance(19)
        c.tick()
        assertTrue(c.running)
        clock.advance(2)
        c.tick()
        assertFalse(c.running)
    }

    @Test
    fun `manual collection model never reuses previous round trace`() = runTest {
        val clock = FakeClock(); val page = FakePage()
        val c = controller(page, clock)
        val other = PageState(url = "https://arena.ai/agent/11111111-2222-3333-4444-555555555555")
        assertEquals("未识别", c.manualCollectionModel(other, ProbeSnapshot(api = true, runId = "r", name = "gpt-5")))
    }
}
