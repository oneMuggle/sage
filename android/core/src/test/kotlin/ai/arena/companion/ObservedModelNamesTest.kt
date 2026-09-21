package ai.arena.companion

import ai.arena.companion.data.ObservedModelNames
import java.io.File
import java.nio.file.Files
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

// ref: reference/Arena模型助手-源码-fyb-0.1.0/src/MainForm.ModelRetention.cs
class ObservedModelNamesTest {

    private fun tempDir(): File = Files.createTempDirectory("observed").toFile()

    @Test
    fun `missing file means nothing observed`() {
        assertEquals(emptyList(), ObservedModelNames(tempDir()).load())
    }

    @Test
    fun `record filters unidentified demo blank and control names and dedupes case-insensitively`() {
        val store = ObservedModelNames(tempDir())
        assertTrue(store.record(listOf("gpt-5", " claude-4 ", "GPT-5", "未识别（探针未加载）", "演示模型 A", "", null, "bad\u0007name", "x".repeat(201))))
        assertEquals(listOf("claude-4", "gpt-5"), store.load())
        assertFalse(store.record("gpt-5"))
        assertTrue(store.record("gemini-2.5-pro"))
        assertEquals(listOf("claude-4", "gemini-2.5-pro", "gpt-5"), store.load())
    }

    @Test
    fun `corrupt cache reads as empty and never widens exclusions`() {
        val dir = tempDir()
        File(dir, ObservedModelNames.FILE_NAME).writeText("{not json")
        val store = ObservedModelNames(dir)
        assertEquals(emptyList(), store.load())
        assertTrue(store.record("gpt-5"))
        assertEquals(listOf("gpt-5"), store.load())
    }

    @Test
    fun `file is a plain json array so the desktop format stays readable`() {
        val dir = tempDir()
        File(dir, ObservedModelNames.FILE_NAME).writeText("[\"gpt-5\",\"claude-4\"]")
        assertEquals(listOf("claude-4", "gpt-5"), ObservedModelNames(dir).load())
    }
}
