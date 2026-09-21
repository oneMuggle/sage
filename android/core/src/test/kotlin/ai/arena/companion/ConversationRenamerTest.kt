package ai.arena.companion

import ai.arena.companion.automation.ConversationRenamer
import ai.arena.companion.automation.RenameState
import ai.arena.companion.automation.RenameTimeoutException
import java.time.Instant
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

class ConversationRenamerTest {

    private val url = "https://arena.ai/agent/11111111-2222-3333-4444-555555555555"

    private class Clock(var now: Instant = Instant.parse("2026-09-20T00:00:00Z")) {
        fun advance(s: Long) { now = now.plusSeconds(s) }
    }

    /** 模拟一个正常响应的重命名页面。 */
    private class FakePage(var title: String? = "旧标题") {
        var menu = false
        var dialog = false
        var draft: String? = null
        var pendingTimes = 0
        val actions = mutableListOf<String>()
        var saveCount = 0

        fun state() = RenameState(linkCount = 1, title = title, renameMenu = menu, renameDialog = dialog)

        fun handle(action: String, value: String): RenameState {
            actions += action
            return when (action) {
                "state" -> state()
                "openMenu" -> {
                    if (pendingTimes > 0) { pendingTimes--; RenameState(pending = true) }
                    else { menu = true; state() }
                }
                "menuRename" -> { dialog = true; state() }
                "fill" -> { draft = value; state() }
                "save" -> { saveCount++; title = draft; dialog = false; menu = false; state() }
                "cleanup" -> state()
                else -> state()
            }
        }
    }

    private fun renamer(page: FakePage, clock: Clock = Clock()) = ConversationRenamer(
        currentUrl = { url },
        executor = { action, value, _ -> page.handle(action, value) },
        clock = { clock.now },
        delay = { },
    )

    @Test
    fun `full rename flow opens menu fills and saves once`() = runTest {
        val page = FakePage()
        renamer(page).rename("gpt-5 · 09-20 10:00", { true }, { })
        assertEquals("gpt-5 · 09-20 10:00", page.title)
        assertEquals(1, page.saveCount)
        assertTrue(page.actions.containsAll(listOf("openMenu", "menuRename", "fill", "save")))
    }

    @Test
    fun `already correct title skips the whole dialog flow`() = runTest {
        val page = FakePage(title = "gpt-5 · 09-20 10:00")
        renamer(page).rename("gpt-5 · 09-20 10:00", { true }, { })
        assertEquals(0, page.saveCount)
        assertTrue(page.actions.none { it == "openMenu" || it == "fill" })
    }

    @Test
    fun `title comparison normalizes whitespace`() {
        assertTrue(ConversationRenamer.hasTitle(RenameState(linkCount = 1, title = "a b"), "a   b"))
        assertTrue(ConversationRenamer.hasTitle(RenameState(linkCount = 1, title = "a b"), "  a b  "))
        // 侧栏入口不唯一时一律不算匹配
        assertTrue(!ConversationRenamer.hasTitle(RenameState(linkCount = 2, title = "a"), "a"))
    }

    @Test
    fun `a submitted save is never replayed on retry`() = runTest {
        // 保存后页面一直不更新标题：第一次调用超时，第二次调用不得重复 save
        val page = FakePage()
        val clock = Clock()
        val r = ConversationRenamer(
            currentUrl = { url },
            executor = { action, value, _ ->
                val s = page.handle(action, value)
                if (action == "save") page.title = "没生效"   // 保存后标题并未变成目标
                if (action == "state") clock.advance(5)
                s
            },
            clock = { clock.now },
            delay = { },
        )
        assertFailsWith<RenameTimeoutException> { r.rename("目标标题", { true }, { }) }
        val savesAfterFirst = page.saveCount
        assertEquals(1, savesAfterFirst)

        // 第二次（用户点"继续"）：saveSubmitted 仍为真，只确认不重放
        assertFailsWith<RenameTimeoutException> { r.rename("目标标题", { true }, { }) }
        assertEquals(savesAfterFirst, page.saveCount)
    }

    @Test
    fun `sidebar entry pending eventually times out`() = runTest {
        val page = FakePage().apply { pendingTimes = 1000 }
        val clock = Clock()
        val r = ConversationRenamer(
            currentUrl = { url },
            executor = { a, v, _ -> page.handle(a, v).also { if (a == "openMenu") clock.advance(2) } },
            clock = { clock.now },
            delay = { },
        )
        val e = assertFailsWith<RenameTimeoutException> { r.rename("x", { true }, { }) }
        assertTrue(e.message!!.contains("侧栏"))
    }

    @Test
    fun `non conversation url is rejected before any action`() = runTest {
        val page = FakePage()
        val r = ConversationRenamer({ "https://arena.ai/agent" }, { a, v, _ -> page.handle(a, v) }, { Instant.now() }, { })
        assertFailsWith<IllegalStateException> { r.rename("x", { true }, { }) }
        assertTrue(page.actions.isEmpty())
    }

    @Test
    fun `pause cancels without dispatching further actions`() = runTest {
        val page = FakePage()
        val r = renamer(page)
        assertFailsWith<CancellationException> { r.rename("x", { false }, { }) }
        assertTrue(page.actions.isEmpty())
    }

    @Test
    fun `script error surfaces as a readable failure`() = runTest {
        val r = ConversationRenamer(
            currentUrl = { url },
            executor = { _, _, _ -> RenameState(error = "找不到重命名菜单") },
            clock = { Instant.now() },
            delay = { },
        )
        val e = assertFailsWith<IllegalStateException> { r.rename("x", { true }, { }) }
        assertEquals("找不到重命名菜单", e.message)
    }
}
