package ai.arena.companion

import ai.arena.companion.automation.AttachmentEntry
import ai.arena.companion.automation.AttachmentPage
import ai.arena.companion.automation.AttachmentUpload
import ai.arena.companion.data.BoundAttachment
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertTrue
import kotlinx.coroutines.runBlocking

// ref: reference/Arena模型助手-源码-fyb-0.1.0/src/AttachmentUpload.cs
class AttachmentUploadTest {

    private val agent = "https://arena.ai/agent"
    private val a = BoundAttachment("a.txt", "/x/a.txt", "00", 1)
    private val b = BoundAttachment("b.png", "/x/b.png", "01", 2)

    private class FakePage : AttachmentPage {
        var ready = false
        var entry: AttachmentEntry? = AttachmentEntry(count = 1, trigger = true, label = "Attach", x = 10.0, y = 20.0, width = 40.0, height = 40.0)
        var deliverResult = true
        val readyCalls = mutableListOf<List<String>>()
        var entryCalls = 0
        val delivered = mutableListOf<List<String>>()
        override suspend fun ready(names: List<String>): Boolean { readyCalls += names; return ready }
        override suspend fun entry(): AttachmentEntry? { entryCalls++; return entry }
        override suspend fun deliver(entry: AttachmentEntry, files: List<BoundAttachment>): Boolean {
            delivered += files.map { it.name }; return deliverResult
        }
    }

    private fun upload(page: FakePage, url: String? = agent, verified: MutableList<Int> = mutableListOf()) =
        AttachmentUpload(page, { url }, verify = { verified += it.count() })

    @Test
    fun `no attachments means nothing is required and check is delegated with an empty list`() = runBlocking {
        val page = FakePage().apply { ready = true }
        val u = upload(page, url = "https://example.com/")
        assertFalse(u.required)
        assertTrue(u.check())                      // 不 Required 时不校验域名（与 C# 一致）
        assertEquals(listOf(emptyList()), page.readyCalls)
        assertTrue(u.prepare())
        assertEquals(0, page.entryCalls)
    }

    @Test
    fun `configure verifies the list and resets the per-round guard`() = runBlocking {
        val page = FakePage()
        val verified = mutableListOf<Int>()
        val u = upload(page, verified = verified)
        u.configure(listOf(a, b))
        assertEquals(listOf(2), verified)
        assertTrue(u.required)
        assertEquals(listOf("a.txt", "b.png"), u.names)
        assertFalse(u.prepare())                   // 第一次：投递
        assertEquals(1, page.delivered.size)
        assertFalse(u.prepare())                   // 同一轮：不再投递
        assertEquals(1, page.delivered.size)
        u.configure(listOf(a))                     // 重新配置 = 新一轮
        assertFalse(u.prepare())
        assertEquals(2, page.delivered.size)
        assertEquals(listOf("a.txt"), page.delivered.last())
    }

    @Test
    fun `prepare delivers exactly once per round and becomes true once the page confirms`() = runBlocking {
        val page = FakePage()
        val u = upload(page)
        u.configure(listOf(a))
        assertFalse(u.prepare())
        assertEquals(1, page.entryCalls)
        assertEquals(listOf(listOf("a.txt")), page.delivered)
        assertFalse(u.prepare()); assertFalse(u.prepare())
        assertEquals(1, page.delivered.size)       // submitted 守卫
        page.ready = true
        assertTrue(u.prepare())
        assertTrue(u.check())
        u.beginRound()
        page.ready = false
        assertFalse(u.prepare())
        assertEquals(2, page.delivered.size)       // 新一轮允许再投递一次
    }

    @Test
    fun `check and stage refuse to run outside arena agent pages when attachments are required`() = runBlocking {
        for (url in listOf(null, "https://example.com/agent", "https://arena.ai/", "http://arena.ai/agent", "https://arena.ai/leaderboard/agent")) {
            val page = FakePage().apply { ready = true }
            val u = upload(page, url = url)
            u.configure(listOf(a))
            val e = assertFailsWith<IllegalStateException> { u.check() }
            assertEquals("仅可向 Arena Agent 页面上传绑定附件", e.message)
            assertFailsWith<IllegalStateException> { u.stage() }
            assertTrue(page.delivered.isEmpty())
        }
        // 具体会话页也允许（限流重试时草稿在同一会话里恢复）
        val page = FakePage().apply { ready = true }
        val u = upload(page, url = "https://arena.ai/agent/11111111-1111-4111-8111-111111111111")
        u.configure(listOf(a))
        assertTrue(u.check())
    }

    @Test
    fun `stage requires exactly one entry with a touchable trigger and a successful delivery`() = runBlocking {
        val page = FakePage()
        val u = upload(page)
        u.configure(listOf(a))

        page.entry = null
        assertEquals("附件入口读取失败", assertFailsWith<IllegalStateException> { u.stage() }.message)
        page.entry = AttachmentEntry(count = 0, reason = "conversation")
        assertEquals("没有找到唯一可用的附件上传入口", assertFailsWith<IllegalStateException> { u.stage() }.message)
        page.entry = AttachmentEntry(count = 2, reason = "ambiguous")
        assertEquals("没有找到唯一可用的附件上传入口", assertFailsWith<IllegalStateException> { u.stage() }.message)
        page.entry = AttachmentEntry(count = 1, trigger = false)
        assertEquals("附件入口无法触发：页面没有可点击的附件按钮", assertFailsWith<IllegalStateException> { u.stage() }.message)
        assertTrue(page.delivered.isEmpty())

        page.entry = AttachmentEntry(count = 1, trigger = true, x = 1.0, y = 2.0, width = 3.0, height = 4.0)
        page.deliverResult = false
        assertEquals("附件入口已变化", assertFailsWith<IllegalStateException> { u.stage() }.message)
        assertEquals(1, page.delivered.size)
        page.deliverResult = true
        u.stage()
        assertEquals(2, page.delivered.size)
        assertTrue(u.lastNote!!.contains("等待网页确认"))
    }

    @Test
    fun `verification failure before staging propagates and nothing is delivered`() = runBlocking {
        val page = FakePage()
        var calls = 0
        val u = AttachmentUpload(page, { agent }, verify = { if (++calls > 1) throw IllegalStateException("绑定附件已丢失或改变：a.txt") })
        u.configure(listOf(a))                     // 第一次 verify 通过
        val e = assertFailsWith<IllegalStateException> { u.prepare() }
        assertTrue(e.message!!.contains("绑定附件已丢失或改变"))
        assertTrue(page.delivered.isEmpty())
    }
}
