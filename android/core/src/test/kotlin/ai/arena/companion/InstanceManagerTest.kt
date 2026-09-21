package ai.arena.companion

import ai.arena.companion.data.InstanceManager
import java.io.File
import java.nio.file.Files
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class InstanceManagerTest {

    private fun tempRoot(): File = Files.createTempDirectory("inst").toFile()

    @Test
    fun `name validation matches the reference regex`() {
        InstanceManager.validateName("账号 A-1_x")
        assertFailsWith<IllegalArgumentException> { InstanceManager.validateName("") }
        assertFailsWith<IllegalArgumentException> { InstanceManager.validateName(" a") }
        assertFailsWith<IllegalArgumentException> { InstanceManager.validateName("a ") }
        assertFailsWith<IllegalArgumentException> { InstanceManager.validateName("a/b") }
        assertFailsWith<IllegalArgumentException> { InstanceManager.validateName("x".repeat(41)) }
    }

    @Test
    fun `rename moves directory and rewrites references`() {
        val root = tempRoot()
        val m = InstanceManager(root)
        val old = m.create("old")
        File(old, "task-settings.json").writeText("""{"attachments":[{"path":"${old.path.replace("\\","\\\\")}/a.txt"}]}""")
        m.rename("old", "new")
        assertFalse(File(root, "old").exists())
        val moved = File(File(root, "new"), "task-settings.json").readText()
        assertTrue(moved.contains("new"))
        assertFalse(moved.contains("${File.separator}old${File.separator}") || moved.contains("/old/"))
    }

    @Test
    fun `rename refuses when the instance is running`() {
        val root = tempRoot()
        val m = InstanceManager(root) { true }
        m.create("a")
        val e = assertFailsWith<IllegalStateException> { m.rename("a", "b") }
        assertTrue(e.message!!.contains("正在运行"))
        assertTrue(File(root, "a").isDirectory)
    }

    @Test
    fun `rename refuses when another running instance references the archive`() {
        val root = tempRoot()
        val plain = InstanceManager(root)
        val a = plain.create("a")
        val b = plain.create("b")
        // b 的归档记录引用 a 的路径
        File(b, "archive-destination.txt").writeText("archive")
        File(File(b, "archive"), "记录.json").also { it.parentFile.mkdirs() }
            .writeText("""[{"profile":"${a.path.replace("\\","\\\\")}"}]""")
        // 只有 b 在运行
        val m = InstanceManager(root) { it.name == "b" }
        val e = assertFailsWith<IllegalStateException> { m.rename("a", "c") }
        assertTrue(e.message!!.contains("b"))
        assertTrue(File(root, "a").isDirectory)   // 未移动
    }

    @Test
    fun `rename to an existing name is rejected`() {
        val root = tempRoot()
        val m = InstanceManager(root)
        m.create("a"); m.create("b")
        assertFailsWith<java.io.IOException> { m.rename("a", "b") }
        assertTrue(File(root, "a").isDirectory)
    }

    @Test
    fun `rename to the same name is rejected`() {
        val root = tempRoot()
        val m = InstanceManager(root)
        m.create("a")
        assertFailsWith<IllegalStateException> { m.rename("a", "a") }
    }

    @Test
    fun `rename of a missing instance is rejected`() {
        val m = InstanceManager(tempRoot())
        assertFailsWith<java.io.FileNotFoundException> { m.rename("nope", "x") }
    }

    @Test
    fun `delete moves to trash by default`() {
        val root = tempRoot()
        val m = InstanceManager(root)
        m.create("a")
        m.delete("a")
        assertFalse(File(root, "a").exists())
        assertTrue(File(root, ".trash").listFiles()!!.any { it.name.startsWith("a-") })
        assertEquals(emptyList(), m.list())   // .trash 不算实例
    }

    @Test
    fun `delete refuses while running`() {
        val root = tempRoot()
        val m = InstanceManager(root) { true }
        m.create("a")
        assertFailsWith<IllegalStateException> { m.delete("a") }
    }

    @Test
    fun `create rejects duplicates`() {
        val m = InstanceManager(tempRoot())
        m.create("a")
        assertFailsWith<IllegalStateException> { m.create("a") }
    }
}
