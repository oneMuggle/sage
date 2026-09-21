// ref: reference/ArenCard/proxy_relay.py
// spec: docs/mcp-android-implementation-plan.md §4.1
//
// 为什么这个中继在安卓上是**必需**而非可选：
// `ProxyController.setProxyOverride()` 的 `ProxyConfig` 不支持 user:password 认证，
// 而参考使用的代理基本都带认证。中继在本机监听一个无认证端口，向上游补上
// Proxy-Authorization。WebView 连 127.0.0.1，认证由中继承担。
package ai.arena.companion.net

import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import java.net.URI
import java.util.Base64
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

/** 上游代理配置。 */
data class UpstreamProxy(
    val host: String,
    val port: Int,
    val username: String? = null,
    val password: String? = null,
) {
    val requiresAuth: Boolean get() = !username.isNullOrEmpty()

    /** `Proxy-Authorization: Basic ...` 的值；无认证返回 null。 */
    fun basicCredentials(): String? {
        if (!requiresAuth) return null
        val raw = "${decode(username!!)}:${decode(password ?: "")}"
        return Base64.getEncoder().encodeToString(raw.toByteArray(Charsets.UTF_8))
    }

    companion object {
        private fun decode(v: String) = try {
            java.net.URLDecoder.decode(v, "UTF-8")
        } catch (_: Exception) { v }

        /** 解析 `http://user:pass@host:port` / `host:port`。无法解析抛出。 */
        fun parse(value: String?): UpstreamProxy {
            val text = (value ?: "").trim()
            if (text.isEmpty()) throw IllegalArgumentException("代理地址为空")
            val uri = try {
                URI(if (text.contains("://")) text else "http://$text")
            } catch (e: Exception) {
                throw IllegalArgumentException("代理地址无法解析：$text")
            }
            val host = uri.host ?: throw IllegalArgumentException("代理地址缺少主机名：$text")
            val port = if (uri.port > 0) uri.port else 80
            val info = uri.userInfo
            val user = info?.substringBefore(':')
            val pass = info?.substringAfter(':', "")
            return UpstreamProxy(host, port, user, pass)
        }
    }
}

/**
 * 构造发往上游的 **最小 CONNECT** 请求。
 *
 * 参考实测：某些代理在 CONNECT 里**只要带 Host 头就拒绝**
 * （最小 CONNECT → 200；+Host → 拒绝；+User-Agent / +Proxy-Connection → 200）。
 * 所以这里除了可选的 Proxy-Authorization 之外**绝不添加任何头**。
 */
fun buildConnectRequest(host: String, port: Int, credentials: String?): String = buildString {
    append("CONNECT $host:$port HTTP/1.0\r\n")
    if (credentials != null) append("Proxy-Authorization: Basic $credentials\r\n")
    append("\r\n")
}

/** 上游 CONNECT 响应是否成功。 */
fun isConnectSuccess(statusLine: String?): Boolean =
    statusLine != null && statusLine.contains(" 200")

private val CONNECT_RE = Regex("""CONNECT\s+([^\s:]+):(\d+)""", RegexOption.IGNORE_CASE)

/** 从客户端请求行解析目标主机端口。 */
fun parseConnectTarget(requestLine: String?): Pair<String, Int>? {
    val m = CONNECT_RE.find(requestLine ?: "") ?: return null
    val port = m.groupValues[2].toIntOrNull() ?: return null
    return m.groupValues[1] to port
}

/**
 * 本地 CONNECT 中继。
 *
 * **端口必须交给系统分配（bind 0）**，不能用固定基数。参考记录了一个真实事故：
 * SO_REUSEADDR 允许多个进程重复绑定同一个 127.0.0.1:20000，实测 11 个进程同时监听
 * 而只有一个在收连接，导致所有实例都从同一条上游出去、**IP 隔离彻底失效**。
 */
class ProxyRelay(private val log: (String) -> Unit = {}) : AutoCloseable {

    private val servers = ConcurrentHashMap<String, RelayServer>()
    private val pool = Executors.newCachedThreadPool { r ->
        Thread(r, "arena-proxy-relay").apply { isDaemon = true }
    }
    private val closed = AtomicBoolean(false)

    private class RelayServer(val socket: ServerSocket, val upstream: UpstreamProxy) {
        val port: Int get() = socket.localPort
    }

    /** 为一条上游分配本地端口；同一条上游复用同一端口。 */
    fun add(upstream: String): Int {
        if (closed.get()) throw IllegalStateException("中继已关闭")
        val key = upstream.trim()
        servers[key]?.let { return it.port }
        val parsed = UpstreamProxy.parse(key)
        // 端口交给系统分配，只监听回环。
        val socket = ServerSocket(0, 64, InetAddress.getByName("127.0.0.1"))
        val server = RelayServer(socket, parsed)
        val existing = servers.putIfAbsent(key, server)
        if (existing != null) { socket.close(); return existing.port }
        pool.execute { acceptLoop(server) }
        log("[relay] 127.0.0.1:${server.port} → ${parsed.host}:${parsed.port}")
        return server.port
    }

    /** 给 WebView `ProxyConfig` 用的无认证本地地址。 */
    fun localAddress(upstream: String): String = "127.0.0.1:${add(upstream)}"

    override fun close() {
        if (!closed.compareAndSet(false, true)) return
        servers.values.forEach { runCatching { it.socket.close() } }
        servers.clear()
        pool.shutdownNow()
    }

    private fun acceptLoop(server: RelayServer) {
        while (!closed.get() && !server.socket.isClosed) {
            val client = try { server.socket.accept() } catch (_: Exception) { return }
            pool.execute { handle(client, server.upstream) }
        }
    }

    private fun handle(client: Socket, upstream: UpstreamProxy) {
        var server: Socket? = null
        try {
            client.soTimeout = 30_000
            val head = readHead(client.getInputStream()) ?: return
            val target = parseConnectTarget(head.lineSequence().firstOrNull())
            if (target == null) {
                client.getOutputStream().write("HTTP/1.1 400 Bad Request\r\n\r\n".toByteArray())
                return
            }
            server = Socket().apply {
                connect(InetSocketAddress(upstream.host, upstream.port), 20_000)
                soTimeout = 30_000
            }
            server.getOutputStream().apply {
                write(buildConnectRequest(target.first, target.second, upstream.basicCredentials())
                    .toByteArray(Charsets.ISO_8859_1))
                flush()
            }
            val response = readHead(server.getInputStream())
            if (!isConnectSuccess(response?.lineSequence()?.firstOrNull())) {
                // 上游不可用时**如实回 502，绝不回退直连**（方案 §4.1）。
                client.getOutputStream().write("HTTP/1.1 502 Bad Gateway\r\n\r\n".toByteArray())
                return
            }
            client.getOutputStream().apply {
                write("HTTP/1.1 200 Connection Established\r\n\r\n".toByteArray())
                flush()
            }
            val up = server
            pool.execute { pump(client.getInputStream(), up.getOutputStream()) }
            pump(up.getInputStream(), client.getOutputStream())
        } catch (_: Exception) {
            // 单条连接失败不影响中继本身。
        } finally {
            runCatching { server?.close() }
            runCatching { client.close() }
        }
    }

    private fun readHead(input: InputStream): String? {
        val buffer = StringBuilder()
        val chunk = ByteArray(1)
        while (buffer.length < 8192) {
            val read = try { input.read(chunk) } catch (_: IOException) { return null }
            if (read <= 0) return if (buffer.isEmpty()) null else buffer.toString()
            buffer.append(chunk[0].toInt().toChar())
            if (buffer.endsWith("\r\n\r\n")) break
        }
        return buffer.toString()
    }

    private fun pump(from: InputStream, to: OutputStream) {
        val buffer = ByteArray(1 shl 14)
        try {
            while (true) {
                val read = from.read(buffer)
                if (read <= 0) break
                to.write(buffer, 0, read)
                to.flush()
            }
        } catch (_: Exception) {
        }
    }
}
