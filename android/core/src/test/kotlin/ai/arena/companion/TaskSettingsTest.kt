package ai.arena.companion

import ai.arena.companion.data.BoundAttachment
import ai.arena.companion.data.TaskSettings
import ai.arena.companion.data.TaskSettingsStore
import java.io.File
import java.nio.file.Files
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

class TaskSettingsTest {

    private fun tempDir(): File = Files.createTempDirectory("task").toFile()

    @Test
    fun `default prompt is the shortest real call`() {
        assertEquals("1+1=", TaskSettings().prompt)
        assertEquals(3.0, TaskSettings().stepPauseSeconds)
        assertEquals(2.0, TaskSettings().stepPauseJitterSeconds)
        assertEquals(0, TaskSettings().roundLimit)
        assertEquals(300, TaskSettings().maximumNoProgressSeconds)
        assertEquals(150, TaskSettings().modelWaitSeconds)
    }

    @Test
    fun `run parameters round-trip and out-of-range values are clamped`() {
        val dir = tempDir()
        val store = TaskSettingsStore(dir)
        store.save(TaskSettings(roundLimit = 5, maximumNoProgressSeconds = 400, modelWaitSeconds = 90))
        val loaded = store.load()
        assertEquals(5, loaded.roundLimit)
        assertEquals(400, loaded.maximumNoProgressSeconds)
        assertEquals(90, loaded.modelWaitSeconds)
        store.save(TaskSettings(roundLimit = -3, maximumNoProgressSeconds = 5, modelWaitSeconds = 1))
        val clamped = store.load()
        assertEquals(0, clamped.roundLimit)
        assertEquals(TaskSettings.MIN_NO_PROGRESS_SECONDS, clamped.maximumNoProgressSeconds)
        assertEquals(TaskSettings.MIN_MODEL_WAIT_SECONDS, clamped.modelWaitSeconds)
    }

    @Test
    fun `settings written before the run parameters existed load with defaults`() {
        val dir = tempDir()
        File(dir, "task-settings.json").writeText(
            """{"prompt":"画一只猫","excludedModels":["gpt-5"],"pauseOnCaptcha":true,"stepPauseSeconds":3.0,"stepPauseJitterSeconds":2.0,"attachments":[]}"""
        )
        val loaded = TaskSettingsStore(dir).load()
        assertEquals("画一只猫", loaded.prompt)
        assertEquals(listOf("gpt-5"), loaded.excludedModels)
        assertEquals(0, loaded.roundLimit)
        assertEquals(300, loaded.maximumNoProgressSeconds)
        assertEquals(150, loaded.modelWaitSeconds)
    }

    @Test
    fun `legacy hi default migrates to new default`() {
        val dir = tempDir()
        val store = TaskSettingsStore(dir)
        store.save(TaskSettings(prompt = "hi"))
        assertEquals("1+1=", store.load().prompt)
    }

    @Test
    fun `user edited prompt is preserved verbatim`() {
        val dir = tempDir()
        val store = TaskSettingsStore(dir)
        store.save(TaskSettings(prompt = "画一只猫"))
        assertEquals("画一只猫", store.load().prompt)
    }

    @Test
    fun `blank prompt falls back to default`() {
        val dir = tempDir()
        val store = TaskSettingsStore(dir)
        store.save(TaskSettings(prompt = "   "))
        assertEquals("1+1=", store.load().prompt)
    }

    @Test
    fun `attachment import is content addressed and re-verified`() {
        val dir = tempDir()
        val store = TaskSettingsStore(dir)
        val src = File(dir, "src.txt").also { it.writeText("hello") }
        val bound = store.import(src)
        assertEquals(5L, bound.bytes)
        assertTrue(bound.path.contains(bound.sha256))
        assertTrue(File(bound.path).isFile)
        TaskSettingsStore.verify(listOf(bound))
    }

    @Test
    fun `empty or missing attachment is rejected`() {
        val dir = tempDir()
        val store = TaskSettingsStore(dir)
        val empty = File(dir, "empty.txt").also { it.writeText("") }
        assertFailsWith<IllegalArgumentException> { store.import(empty) }
        assertFailsWith<IllegalArgumentException> { store.import(File(dir, "nope.txt")) }
    }

    @Test
    fun `duplicate attachment names are rejected`() {
        val dir = tempDir()
        val a = BoundAttachment("a.txt", File(dir, "a").path, "h", 1)
        assertFailsWith<IllegalStateException> { TaskSettingsStore.verify(listOf(a, a.copy(sha256 = "h2"))) }
    }

    @Test
    fun `changed attachment bytes fail verification`() {
        val dir = tempDir()
        val store = TaskSettingsStore(dir)
        val src = File(dir, "src.txt").also { it.writeText("hello") }
        val bound = store.import(src)
        File(bound.path).writeText("tampered")
        assertFailsWith<IllegalStateException> { TaskSettingsStore.verify(listOf(bound)) }
    }

    @Test
    fun `attachment paths inside the tree are stored relative`() {
        val dir = tempDir()
        val store = TaskSettingsStore(dir)
        val src = File(dir, "src.txt").also { it.writeText("hello") }
        val bound = store.import(src)
        val settings = TaskSettings(attachments = mutableListOf(bound))
        store.save(settings)
        val raw = File(dir, "task-settings.json").readText()
        assertTrue(raw.contains("Attachments"))
        // 存的是相对路径，不含盘符/根前缀
        assertTrue(!raw.contains(dir.absolutePath.replace("\\", "\\\\")))
        // 读回来是绝对路径且可用
        assertTrue(File(store.load().attachments[0].path).isFile)
    }
}
