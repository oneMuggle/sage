// ref: reference/Arena模型助手-源码-fyb-0.1.0/src/ConversationIdentity.cs
// spec: docs/mcp-android-implementation-plan.md §3.2
package ai.arena.companion.identity

import java.net.URI

/**
 * URL 规范化是幂等性的地基，必须与 C# 版 1:1。
 * 只认 https + 443 + 空 UserInfo + host ∈ {arena.ai, arena-demo.local}。
 */
object ConversationIdentity {

    private val UUID_PATH = Regex(
        "^/agent/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
    )
    private val DEMO_PATH = Regex("^/agent/demo-[1-9][0-9]*$")

    /** 对应 C# Route()；不可识别返回 null。 */
    fun route(value: String?): String? {
        if (value.isNullOrBlank()) return null
        val u = try {
            URI(value)
        } catch (_: Exception) {
            return null
        }
        if (!u.isAbsolute) return null
        if (u.scheme != "https") return null
        // C# Uri 对 https 缺省端口填 443；Java URI 给 -1，两者语义等价。
        if (u.port != -1 && u.port != 443) return null
        if (!u.userInfo.isNullOrEmpty()) return null
        val host = u.host ?: return null
        if (host != "arena.ai" && host != "arena-demo.local") return null
        val raw = u.rawPath ?: return null
        val path = raw.trimEnd('/')
        if (path == "/agent") return "https://$host$path"
        if (UUID_PATH.matches(path)) return "https://$host${path.lowercase()}"
        if (host == "arena-demo.local" && DEMO_PATH.matches(path)) return "https://$host$path"
        return null
    }

    /** 比较规范化结果而非原始字符串。 */
    fun same(a: String?, b: String?): Boolean {
        val x = route(a) ?: return false
        return x == route(b)
    }

    /** 只认 arena.ai 上的真实具体会话。 */
    fun created(value: String?): String? {
        val r = route(value) ?: return null
        return if (r.startsWith("https://arena.ai/agent/")) r else null
    }

    fun isNew(value: String?): Boolean {
        val r = route(value)
        return r == "https://arena.ai/agent" || r == "https://arena-demo.local/agent"
    }

    fun isTransition(origin: String?, value: String?): Boolean {
        if (!isNew(origin)) return false
        val a = route(origin) ?: return false
        val b = route(value) ?: return false
        return b.startsWith("$a/")
    }
}
