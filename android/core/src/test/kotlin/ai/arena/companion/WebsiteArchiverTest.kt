package ai.arena.companion

import ai.arena.companion.automation.ArchivePausedException
import ai.arena.companion.automation.ArchiveStepResult
import ai.arena.companion.automation.WebsiteArchiver
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNotEquals
import kotlin.test.assertNotNull
import kotlinx.coroutines.runBlocking

// ref: reference/Arena模型助手-源码-fyb-0.1.0/src/WebPage.ModelArchive.cs
class WebsiteArchiverTest {

    private val a = "https://arena.ai/agent/11111111-1111-4111-8111-111111111111"
    private val b = "https://arena.ai/agent/22222222-2222-4222-8222-222222222222"

    private class Script(
        vararg results: ArchiveStepResult?,
        private val afterwards: ArchiveStepResult = ArchiveStepResult(pending = true),
    ) {
        private val queue = results.toMutableList()
        val calls = mutableListOf<List<String?>>()
        val delays = mutableListOf<Long>()
        suspend fun step(target: String, token: String, prompt: String?, stamp: String?): ArchiveStepResult? {
            calls += listOf(target, token, prompt, stamp)
            return if (queue.isEmpty()) afterwards else queue.removeAt(0)
        }
    }

    private fun archiver(script: Script, url: () -> String? = { a }, attempts: Int = 120) = WebsiteArchiver(
        step = script::step,
        currentUrl = url,
        isAllowed = { it != null && it.startsWith("https://arena.ai/agent") },
        delay = { script.delays += it },
        attempts = attempts,
        intervalMillis = 250,
    )

    @Test
    fun `polls until confirmed and reuses one token per target`() = runBlocking {
        val script = Script(
            ArchiveStepResult(pending = true), ArchiveStepResult(pending = true), ArchiveStepResult(confirmed = true),
            afterwards = ArchiveStepResult(confirmed = true),
        )
        val archiver = archiver(script)
        archiver.archive("$a/?x=1", "1+1=", "1:u1:a1:sig") { true }
        assertEquals(3, script.calls.size)
        assertEquals(listOf(250L, 250L), script.delays)
        val token = archiver.token
        assertNotNull(token)
        assertEquals(32, token.length)
        script.calls.forEach {
            assertEquals(a, it[0]); assertEquals(token, it[1]); assertEquals("1+1=", it[2]); assertEquals("1:u1:a1:sig", it[3])
        }
        // 同一目标再次归档：token 不变（页面状态得以延续）；换目标：token 更新。
        archiver.archive(a, "1+1=", "1:u1:a1:sig") { true }
        assertEquals(token, archiver.token)
        archiver.archive(b, "1+1=", "2:u2:a2:sig") { true }
        assertNotEquals(token, archiver.token)
    }

    @Test
    fun `only real arena conversations can be archived`() = runBlocking {
        val script = Script()
        for (url in listOf(null, "", "https://arena.ai/agent", "https://example.invalid/agent/11111111-1111-4111-8111-111111111111")) {
            val e = assertFailsWith<IllegalStateException> { archiver(script).archive(url, "1+1=", "s") { true } }
            assertEquals("仅支持真实 Arena 当前对话的归档", e.message)
        }
        assertEquals(0, script.calls.size)
    }

    @Test
    fun `page error is surfaced verbatim and nothing else is clicked`() = runBlocking {
        val script = Script(ArchiveStepResult(error = "当前菜单没有唯一可用的归档入口；不会改用删除"))
        val e = assertFailsWith<IllegalStateException> { archiver(script).archive(a, "1+1=", "s") { true } }
        assertEquals("当前菜单没有唯一可用的归档入口；不会改用删除", e.message)
        assertEquals(1, script.calls.size)
    }

    @Test
    fun `missing bridge result is a failure not a success`() = runBlocking {
        val script = Script(null)
        val e = assertFailsWith<IllegalStateException> { archiver(script).archive(a, "1+1=", "s") { true } }
        assertEquals("归档结果未确认", e.message)
    }

    @Test
    fun `inactive before a step cancels without calling the page`() = runBlocking {
        val script = Script()
        val e = assertFailsWith<IllegalStateException> { archiver(script).archive(a, "1+1=", "s") { false } }
        assertEquals("归档操作已取消；不会继续点击", e.message)
        assertEquals(0, script.calls.size)
    }

    @Test
    fun `pause after a step is reported as paused even when the page confirmed`() = runBlocking {
        val script = Script(ArchiveStepResult(confirmed = true))
        var active = true
        val e = assertFailsWith<ArchivePausedException> {
            archiver(script).archive(a, "1+1=", "s") { active.also { active = false } }
        }
        assertEquals("归档已暂停；结果将在继续时确认", e.message)
    }

    @Test
    fun `navigation away from arena stops the loop`() = runBlocking {
        val script = Script()
        val e = assertFailsWith<IllegalStateException> {
            archiver(script, url = { "https://accounts.google.com/" }).archive(a, "1+1=", "s") { true }
        }
        assertEquals("页面已改变，归档已停止", e.message)
        assertEquals(0, script.calls.size)
        val e2 = assertFailsWith<IllegalStateException> { archiver(script, url = { null }).archive(a, "1+1=", "s") { true } }
        assertEquals("页面已改变，归档已停止", e2.message)
    }

    @Test
    fun `timeout after all attempts never falls through as success`() = runBlocking {
        val script = Script()
        val e = assertFailsWith<IllegalStateException> { archiver(script, attempts = 5).archive(a, "1+1=", "s") { true } }
        assertEquals("归档尚未获得成功确认，已暂停。请检查网页；不会自动点击删除或继续下一条。", e.message)
        assertEquals(5, script.calls.size)
        assertEquals(5, script.delays.size)
    }
}
