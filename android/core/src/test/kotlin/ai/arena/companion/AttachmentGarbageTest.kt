package ai.arena.companion

import ai.arena.companion.data.AttachmentGarbage
import ai.arena.companion.data.TaskSettings
import ai.arena.companion.data.TaskSettingsStore
import java.io.File
import java.nio.file.Files
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class AttachmentGarbageTest {

    private fun instance(): File = Files.createTempDirectory("attach").toFile()

    private fun importFile(store: TaskSettingsStore, dir: File, name: String, body: String) =
        store.import(File(dir, name).apply { writeText(body) })

    @Test
    fun `identical content shares one hash directory and is counted twice`() {
        val d = instance()
        val store = TaskSettingsStore(d)
        val src = Files.createTempDirectory("src").toFile()
        val a = importFile(store, src, "a.txt", "same")
        val b = importFile(store, src, "b.txt", "same")
        assertEquals(a.sha256, b.sha256)

        val s1 = TaskSettings(attachments = mutableListOf(a))
        val s2 = TaskSettings(attachments = mutableListOf(b))
        assertEquals(mapOf(a.sha256 to 2), AttachmentGarbage.referenceCounts(listOf(s1, s2)))
    }

    @Test
    fun `a directory still referenced elsewhere is never collected`() {
        val d = instance()
        val store = TaskSettingsStore(d)
        val src = Files.createTempDirectory("src").toFile()
        val shared = importFile(store, src, "a.txt", "same")
        importFile(store, src, "b.txt", "same")     // 同内容，同目录
        val keep = TaskSettings(attachments = mutableListOf(shared))

        assertTrue(AttachmentGarbage.unreferenced(d, listOf(keep)).isEmpty())
        assertEquals(0 to 0L, AttachmentGarbage.collect(d, listOf(keep)))
        assertTrue(File(File(d, "Attachments"), shared.sha256).isDirectory)
    }

    @Test
    fun `unreferenced directories are listed and collected`() {
        val d = instance()
        val store = TaskSettingsStore(d)
        val src = Files.createTempDirectory("src").toFile()
        val kept = importFile(store, src, "keep.txt", "keep")
        val dropped = importFile(store, src, "drop.txt", "drop")
        val settings = TaskSettings(attachments = mutableListOf(kept))

        val stale = AttachmentGarbage.unreferenced(d, listOf(settings))
        assertEquals(listOf(dropped.sha256), stale.map { it.name })

        val (count, bytes) = AttachmentGarbage.collect(d, listOf(settings))
        assertEquals(1, count)
        assertEquals(4L, bytes)
        assertTrue(File(File(d, "Attachments"), kept.sha256).isDirectory)
        assertTrue(!File(File(d, "Attachments"), dropped.sha256).exists())
    }

    @Test
    fun `dry run reports without deleting anything`() {
        val d = instance()
        val store = TaskSettingsStore(d)
        val src = Files.createTempDirectory("src").toFile()
        val dropped = importFile(store, src, "drop.txt", "drop")

        val (count, bytes) = AttachmentGarbage.collect(d, emptyList(), dryRun = true)
        assertEquals(1, count)
        assertEquals(4L, bytes)
        assertTrue(File(File(d, "Attachments"), dropped.sha256).isDirectory)
    }

    @Test
    fun `missing attachments directory is not an error`() {
        val d = instance()
        assertTrue(AttachmentGarbage.unreferenced(d, emptyList()).isEmpty())
        assertEquals(0 to 0L, AttachmentGarbage.collect(d, emptyList()))
    }
}
