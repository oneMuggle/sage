package ai.arena.companion

import ai.arena.companion.net.ProxyMode
import ai.arena.companion.net.ProxySettings
import ai.arena.companion.net.ProxySettingsStore
import java.io.File
import java.nio.file.Files
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull
import kotlin.test.assertTrue

class ProxySettingsTest {

    private fun tmp(): File = Files.createTempDirectory("proxy-settings").toFile()

    @Test
    fun `system mode yields no proxy uri`() {
        assertNull(ProxySettings().proxyUri())
        assertNull(ProxySettings().upstream())
    }

    @Test
    fun `clash is rejected explicitly instead of silently becoming direct`() {
        val e = assertFailsWith<IllegalArgumentException> { ProxyMode.parse("clash") }
        assertTrue(e.message!!.contains("Clash"))
        assertFailsWith<IllegalArgumentException> { ProxySettings(mode = "clash").proxyUri() }
    }

    @Test
    fun `unknown mode is rejected`() {
        assertFailsWith<IllegalArgumentException> { ProxySettings(mode = "ftp", port = 1).proxyUri() }
    }

    @Test
    fun `port must be in range`() {
        assertFailsWith<IllegalArgumentException> { ProxySettings("http", "1.2.3.4", 0).proxyUri() }
        assertFailsWith<IllegalArgumentException> { ProxySettings("http", "1.2.3.4", 65536).proxyUri() }
        assertEquals("http://1.2.3.4:65535", ProxySettings("http", "1.2.3.4", 65535).proxyUri())
    }

    @Test
    fun `host must not carry scheme port user or path`() {
        for (bad in listOf("http://1.2.3.4", "1.2.3.4:8080", "u@1.2.3.4", "1.2.3.4/x", "", "-a.com", "a..com")) {
            assertFailsWith<IllegalArgumentException>("should reject: $bad") {
                ProxySettings("http", bad, 8080).proxyUri()
            }
        }
    }

    @Test
    fun `ipv6 is bracketed and already bracketed input is accepted`() {
        assertEquals("socks5://[::1]:1080", ProxySettings("socks5", "::1", 1080).proxyUri())
        assertEquals("socks5://[::1]:1080", ProxySettings("socks5", "[::1]", 1080).proxyUri())
    }

    @Test
    fun `upstream embeds percent encoded credentials`() {
        val s = ProxySettings("http", "p.example.com", 8080, "user@mail", "p ss")
        assertEquals("http://user%40mail:p%20ss@p.example.com:8080", s.upstream())
    }

    @Test
    fun `store round trips and validates on save`() {
        val dir = tmp()
        val store = ProxySettingsStore(dir)
        assertEquals(ProxySettings(), store.load())      // 文件不存在 → 默认
        val value = ProxySettings("http", "1.2.3.4", 8080, "u", "p")
        store.save(value)
        assertEquals(value, store.load())
        assertFailsWith<IllegalArgumentException> { store.save(ProxySettings("http", "1.2.3.4", 0)) }
    }

    @Test
    fun `load rejects a corrupt or invalid config instead of falling back`() {
        val dir = tmp()
        File(dir, "proxy-settings.json").writeText("{ not json")
        assertFailsWith<java.io.IOException> { ProxySettingsStore(dir).load() }

        val dir2 = tmp()
        File(dir2, "proxy-settings.json").writeText("""{"host":"1.2.3.4","port":8080}""")
        // 缺 mode 的老配置按默认方式（跟随系统）迁移，保留其余字段并回写，不再阻断启动。
        val healed = ProxySettingsStore(dir2).load()
        assertEquals("system", healed.mode)
        assertEquals("1.2.3.4", healed.host)
        assertEquals(8080, healed.port)
        assertEquals(healed, ProxySettingsStore(dir2).load())

        val dir3 = tmp()
        File(dir3, "proxy-settings.json").writeText("""{"mode":"http","host":"1.2.3.4","port":0}""")
        assertFailsWith<IllegalArgumentException> { ProxySettingsStore(dir3).load() }
    }

    @Test
    fun `copy carries settings to a new instance directory`() {
        val a = tmp(); val b = tmp()
        val value = ProxySettings("socks5", "example.com", 1080)
        ProxySettingsStore(a).save(value)
        ProxySettingsStore.copy(a, b)
        assertEquals(value, ProxySettingsStore(b).load())
    }

    @Test
    fun `save always writes the mode field so a default config can be loaded back`() {
        val dir = tmp()
        val store = ProxySettingsStore(dir)
        store.save(ProxySettings())   // 全默认值 = 跟随系统
        val raw = File(dir, "proxy-settings.json").readText(Charsets.UTF_8)
        assertTrue(raw.contains("\"mode\""),
            "默认配置也必须落盘 mode，否则 load() 会拒收自己写出来的文件：$raw")
        assertEquals(ProxySettings(), store.load())
    }

    @Test
    fun `mode must be a real json key not just text inside a value`() {
        val dir = tmp()
        File(dir, "proxy-settings.json").writeText(
            """{"note":"mode","host":"1.2.3.4","port":8080}""")
        // 值里出现 "mode" 不算数：仍按「缺 mode 的老配置」迁移成默认跟随系统（旧写入器只省略
        // 默认值），绝不把文本里的 mode 当成真配置、也不静默变成直连。
        val loaded = ProxySettingsStore(dir).load()
        assertEquals("system", loaded.mode)
        val healed = File(dir, "proxy-settings.json").readText(Charsets.UTF_8)
        assertTrue(healed.contains("\"mode\""), "自愈后必须落盘 mode：$healed")
        assertEquals(loaded, ProxySettingsStore(dir).load())
    }

    @Test
    fun `an empty config left by the pre-fix writer is migrated instead of blocking startup`() {
        val dir = tmp()
        File(dir, "proxy-settings.json").writeText("{}")
        val store = ProxySettingsStore(dir)
        assertEquals(ProxySettings(), store.load())
        // 必须就地改写回完整格式，否则下次启动还会读到 `{}`，又得靠人手去设置页保存一次。
        val raw = File(dir, "proxy-settings.json").readText(Charsets.UTF_8)
        assertTrue(raw.contains("\"mode\""), "自愈后必须落盘 mode：$raw")
        assertEquals(ProxySettings(), store.load())
    }
}
