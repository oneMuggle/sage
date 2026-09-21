package ai.arena.companion

import ai.arena.companion.data.ArchiveEntry
import ai.arena.companion.data.ArchiveStore
import java.io.File
import java.nio.file.Files
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class ArchiveStoreTest {

    private fun tempRoot(): File = Files.createTempDirectory("archive").toFile()

    private fun entry(id: String, model: String?, uuid: String, at: String = "2026-09-20 10:00:00") =
        ArchiveEntry(
            id = id,
            title = "$model · 09-20 10:00",
            model = model,
            url = "https://arena.ai/agent/$uuid",
            collectedAt = at,
        )

    private val u1 = "11111111-1111-1111-1111-111111111111"
    private val u2 = "22222222-2222-2222-2222-222222222222"

    @Test
    fun `save creates model dir manifest and summary`() {
        val root = tempRoot()
        val store = ArchiveStore(root)
        store.save(entry("a", "gpt-5", u1))
        assertTrue(File(root, "记录.json").isFile)
        assertTrue(File(root, "汇总.md").isFile)
        assertTrue(File(File(root, "gpt-5"), "清单.md").isFile)
        assertTrue(File(root, "汇总.md").readText().contains("gpt-5"))
    }

    @Test
    fun `same conversation archived twice is idempotent`() {
        val root = tempRoot()
        val store = ArchiveStore(root)
        store.save(entry("a", "gpt-5", u1))
        store.save(entry("a", "gpt-5", u1))
        assertEquals(1, store.all().size)
    }

    @Test
    fun `blank model falls back to unidentified folder`() {
        val root = tempRoot()
        val store = ArchiveStore(root)
        val saved = store.save(entry("a", null, u1))
        assertEquals("未识别", saved.modelFolder)
        assertTrue(File(root, "未识别").isDirectory)
    }

    @Test
    fun `model name with slash is sanitized`() {
        assertEquals("zai-org_GLM-5.3-Flash", ArchiveStore.sanitizeSegment("zai-org/GLM-5.3-Flash"))
        assertEquals("a_b", ArchiveStore.sanitizeSegment("a:b "))
        assertEquals("x", ArchiveStore.sanitizeSegment("  x. "))
    }

    @Test
    fun `invalid conversation url is never archived`() {
        val store = ArchiveStore(tempRoot())
        assertFailsWith<IllegalStateException> {
            store.save(ArchiveEntry(id = "a", url = "https://arena.ai/agent"))
        }
        assertFailsWith<IllegalStateException> {
            store.save(ArchiveEntry(id = "b", url = "https://evil.ai/agent/$u1"))
        }
    }

    @Test
    fun `delete removes entry and empty model directory`() {
        val root = tempRoot()
        val store = ArchiveStore(root)
        store.save(entry("a", "gpt-5", u1))
        val removed = store.delete("a")
        assertEquals("a", removed?.id)
        assertEquals(0, store.all().size)
        assertFalse(File(root, "gpt-5").exists())
        // 汇总仍然存在，只是计数归零
        assertTrue(File(root, "汇总.md").readText().contains("共 0 条会话"))
    }

    @Test
    fun `delete keeps model directory when siblings remain`() {
        val root = tempRoot()
        val store = ArchiveStore(root)
        store.save(entry("a", "gpt-5", u1))
        store.save(entry("b", "gpt-5", u2, at = "2026-09-20 11:00:00"))
        store.delete("a")
        assertTrue(File(File(root, "gpt-5"), "清单.md").isFile)
        assertTrue(File(File(root, "gpt-5"), "清单.md").readText().contains("共 1 条会话"))
    }

    @Test
    fun `deleteMany is all or nothing`() {
        val root = tempRoot()
        val store = ArchiveStore(root)
        store.save(entry("a", "gpt-5", u1))
        assertFailsWith<IllegalStateException> { store.deleteMany(listOf("a", "missing")) }
        assertEquals(1, store.all().size)   // 未删除任何记录
    }

    @Test
    fun `markExported only touches export fields`() {
        val root = tempRoot()
        val store = ArchiveStore(root)
        store.save(entry("a", "gpt-5", u1))
        val updated = store.markExported("a", "/sdcard/out", "2026-09-20 12:00:00")
        assertEquals("/sdcard/out", updated?.exportedFolder)
        assertTrue(File(File(root, "gpt-5"), "清单.md").isFile)
        assertEquals(null, store.markExported("missing", "/x", null))
    }

    @Test
    fun `pipe in title is escaped in markdown tables`() {
        val root = tempRoot()
        val store = ArchiveStore(root)
        val saved = store.save(entry("a", "a|b", u1))
        // 模型名里的 | 先被净化成目录名 a_b，汇总表里不会出现裸竖线
        assertEquals("a_b", saved.modelFolder)
        // 标题未净化，写进清单表时必须转义
        assertTrue(File(File(root, "a_b"), "清单.md").readText().contains("a\\|b"))
    }

    @Test
    fun `recordRound tracks multi-round model evolution and flags drift`() {
        val e0 = entry("conv-1", "gpt-6-luna", u1)
        assertFalse(e0.modelDrifted)
        assertEquals(0, e0.modelHistory.size)

        val e1 = e0.recordRound(1, "gpt-6-luna", "gpt-6-luna-max", 1200L)
        assertFalse(e1.modelDrifted)
        assertEquals(1, e1.modelHistory.size)
        assertEquals("gpt-6-luna", e1.model)

        val e2 = e1.recordRound(2, "gpt-6-luna", "gpt-6-luna-max", 980L)
        assertFalse(e2.modelDrifted)
        assertEquals(2, e2.modelHistory.size)

        val e3 = e2.recordRound(3, "claude-3-7-sonnet", "fable-5.1-high", 2400L)
        assertTrue(e3.modelDrifted)
        assertEquals(3, e3.modelHistory.size)
        assertEquals("claude-3-7-sonnet", e3.model)

        val root = tempRoot()
        val store = ArchiveStore(root)
        store.save(e3.copy(accountId = "acct-99", creditsRemaining = 14500L))
        val loaded = store.all().first { it.id == "conv-1" }
        assertEquals("acct-99", loaded.accountId)
        assertEquals(14500L, loaded.creditsRemaining)
        assertTrue(loaded.modelDrifted)
        assertEquals(3, loaded.modelHistory.size)
    }
}
