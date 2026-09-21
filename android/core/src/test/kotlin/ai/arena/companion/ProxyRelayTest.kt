package ai.arena.companion

import ai.arena.companion.net.ProxyRelay
import ai.arena.companion.net.UpstreamProxy
import ai.arena.companion.net.buildConnectRequest
import ai.arena.companion.net.isConnectSuccess
import ai.arena.companion.net.parseConnectTarget
import java.io.BufferedReader
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import kotlin.concurrent.thread
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class ProxyRelayTest {

    @Test
    fun `upstream parsing handles credentials and bare host port`() {
        val a = UpstreamProxy.parse("http://u:p@1.2.3.4:8080")
        assertEquals("1.2.3.4", a.host); assertEquals(8080, a.port)
        assertTrue(a.requiresAuth)

        val b = UpstreamProxy.parse("1.2.3.4:3128")
        assertEquals(3128, b.port)
        assertFalse(b.requiresAuth)
        assertNull(b.basicCredentials())

        assertFailsWith<IllegalArgumentException> { UpstreamProxy.parse("") }
        assertFailsWith<IllegalArgumentException> { UpstreamProxy.parse("http://") }
    }

    @Test
    fun `percent encoded credentials are decoded before base64`() {
        val p = UpstreamProxy.parse("http://user%40mail:p%3Ass@h:1")
        val decoded = String(java.util.Base64.getDecoder().decode(p.basicCredentials()!!))
        assertEquals("user@mail:p:ss", decoded)
    }

    @Test
    fun `connect request is minimal and never carries a Host header`() {
        val req = buildConnectRequest("arena.ai", 443, null)
        assertEquals("CONNECT arena.ai:443 HTTP/1.0\r\n\r\n", req)
        assertFalse(req.contains("Host", ignoreCase = true))

        val authed = buildConnectRequest("arena.ai", 443, "Zm9v")
        assertTrue(authed.contains("Proxy-Authorization: Basic Zm9v"))
        assertFalse(authed.contains("Host:", ignoreCase = true))
        // 除请求行与认证头外没有别的头
        assertEquals(2, authed.trimEnd('\r', '\n').split("\r\n").size)
    }

    @Test
    fun `connect target parsing`() {
        assertEquals("arena.ai" to 443, parseConnectTarget("CONNECT arena.ai:443 HTTP/1.1"))
        assertNull(parseConnectTarget("GET / HTTP/1.1"))
        assertNull(parseConnectTarget(null))
    }

    @Test
    fun `connect success detection`() {
        assertTrue(isConnectSuccess("HTTP/1.1 200 Connection Established"))
        assertFalse(isConnectSuccess("HTTP/1.1 407 Proxy Authentication Required"))
        assertFalse(isConnectSuccess(null))
    }

    @Test
    fun `same upstream reuses one port and ports are system assigned`() {
        ProxyRelay().use { relay ->
            val a = relay.add("http://u:p@127.0.0.1:1")
            val b = relay.add("http://u:p@127.0.0.1:1")
            val c = relay.add("http://u:p@127.0.0.1:2")
            assertEquals(a, b)
            assertTrue(a != c)
            // 系统分配，绝不是固定基数 20000
            assertTrue(a > 1024)
            assertEquals("127.0.0.1:$a", relay.localAddress("http://u:p@127.0.0.1:1"))
        }
    }

    @Test
    fun `relay tunnels through an authenticating upstream`() {
        // 一个最小的假上游代理：校验认证头、拒绝带 Host 的 CONNECT、然后回显
        val upstream = ServerSocket(0, 8, InetAddress.getByName("127.0.0.1"))
        var sawHost = false
        var sawAuth: String? = null
        thread(isDaemon = true) {
            val client = upstream.accept()
            val reader = client.getInputStream().bufferedReader(Charsets.ISO_8859_1)
            while (true) {
                val line = reader.readLine() ?: break
                if (line.isEmpty()) break
                if (line.startsWith("Host", true)) sawHost = true
                if (line.startsWith("Proxy-Authorization", true)) sawAuth = line.substringAfter("Basic ").trim()
            }
            client.getOutputStream().apply {
                write("HTTP/1.1 200 Connection Established\r\n\r\n".toByteArray()); flush()
            }
            // 隧道建立后回显一行
            val payload = ByteArray(5)
            client.getInputStream().read(payload)
            client.getOutputStream().apply { write(payload); flush() }
        }

        ProxyRelay().use { relay ->
            val port = relay.add("http://user:pass@127.0.0.1:${upstream.localPort}")
            Socket("127.0.0.1", port).use { s ->
                s.soTimeout = 5000
                s.getOutputStream().apply {
                    write("CONNECT arena.ai:443 HTTP/1.1\r\nHost: arena.ai\r\n\r\n".toByteArray()); flush()
                }
                val reader: BufferedReader = s.getInputStream().bufferedReader(Charsets.ISO_8859_1)
                assertTrue(reader.readLine().contains("200"))
                reader.readLine()   // 空行
                s.getOutputStream().apply { write("hello".toByteArray()); flush() }
                val echoed = CharArray(5)
                reader.read(echoed)
                assertEquals("hello", String(echoed))
            }
        }
        // 客户端带了 Host，但中继发往上游的 CONNECT 必须不带
        assertFalse(sawHost)
        assertEquals("user:pass", String(java.util.Base64.getDecoder().decode(sawAuth!!)))
        upstream.close()
    }

    @Test
    fun `unreachable upstream returns 502 and never falls back to direct`() {
        val dead = ServerSocket(0).also { it.close() }.localPort
        ProxyRelay().use { relay ->
            val port = relay.add("http://127.0.0.1:$dead")
            Socket("127.0.0.1", port).use { s ->
                s.soTimeout = 5000
                s.getOutputStream().apply {
                    write("CONNECT arena.ai:443 HTTP/1.1\r\n\r\n".toByteArray()); flush()
                }
                val line = s.getInputStream().bufferedReader(Charsets.ISO_8859_1).readLine()
                // 要么 502，要么直接断开——都不是"连上了"
                assertTrue(line == null || line.contains("502"), "unexpected: $line")
            }
        }
    }

    @Test
    fun `upstream rejection is surfaced as 502`() {
        val upstream = ServerSocket(0, 8, InetAddress.getByName("127.0.0.1"))
        thread(isDaemon = true) {
            val c = upstream.accept()
            val r = c.getInputStream().bufferedReader(Charsets.ISO_8859_1)
            while (true) { val l = r.readLine() ?: break; if (l.isEmpty()) break }
            c.getOutputStream().apply {
                write("HTTP/1.1 407 Proxy Authentication Required\r\n\r\n".toByteArray()); flush()
            }
        }
        ProxyRelay().use { relay ->
            val port = relay.add("http://127.0.0.1:${upstream.localPort}")
            Socket("127.0.0.1", port).use { s ->
                s.soTimeout = 5000
                s.getOutputStream().apply {
                    write("CONNECT arena.ai:443 HTTP/1.1\r\n\r\n".toByteArray()); flush()
                }
                assertTrue(s.getInputStream().bufferedReader(Charsets.ISO_8859_1).readLine()!!.contains("502"))
            }
        }
        upstream.close()
    }

    @Test
    fun `non connect request is rejected`() {
        ProxyRelay().use { relay ->
            val port = relay.add("http://127.0.0.1:1")
            Socket("127.0.0.1", port).use { s ->
                s.soTimeout = 5000
                s.getOutputStream().apply { write("GET / HTTP/1.1\r\n\r\n".toByteArray()); flush() }
                assertTrue(s.getInputStream().bufferedReader(Charsets.ISO_8859_1).readLine()!!.contains("400"))
            }
        }
    }

    @Test
    fun `closed relay refuses new upstreams`() {
        val relay = ProxyRelay()
        relay.add("http://127.0.0.1:1")
        relay.close()
        assertFailsWith<IllegalStateException> { relay.add("http://127.0.0.1:2") }
    }
}
