// ref: reference/Arena模型助手-源码-fyb-0.1.0/src/ProxySettings.cs
// spec: docs/mcp-android-implementation-plan.md §4.1
package ai.arena.companion.net

import ai.arena.companion.data.AtomicFiles
import java.io.File
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject

/** 代理方式。C# 的 `clash` 在安卓版**明确不做**（方案「明确不做：Clash 节点运行时」）。 */
enum class ProxyMode(val wire: String) {
    SYSTEM("system"), HTTP("http"), SOCKS5("socks5");

    companion object {
        fun parse(value: String?): ProxyMode {
            val v = (value ?: "").trim().lowercase()
            // ref: ProxySettings.cs:L19 —— C# 在这里处理 clash；安卓版不实现 Clash 运行时，
            // 于是把它变成一条明确的拒绝，而不是悄悄当成 system（那等于回退直连）。
            if (v == "clash") throw IllegalArgumentException(
                "安卓版不支持 Clash 订阅节点，请改用 HTTP / Mixed 或 SOCKS5 代理。")
            return entries.firstOrNull { it.wire == v }
                ?: throw IllegalArgumentException("请选择跟随系统、HTTP / Mixed 或 SOCKS5。")
        }
    }
}

private val HOST_RE = Regex("^[A-Za-z0-9.-]+$")

/**
 * 代理配置。校验规则逐条对齐 C#：
 * - 端口 1–65535（ref: ProxySettings.cs:L21）
 * - 主机只填 IP 或主机名，**不带协议 / 端口 / 用户名 / 路径**（ref: L26-L27）
 * - IPv6 用方括号包裹（ref: L23-L25）
 */
@Serializable
data class ProxySettings(
    val mode: String = ProxyMode.SYSTEM.wire,
    val host: String = "127.0.0.1",
    val port: Int = 0,
    /** 上游认证；C# 桌面端靠浏览器弹窗，安卓走 ProxyRelay 注入，所以配置里要能存。 */
    val username: String = "",
    val password: String = "",
) {
    /** 返回 `http://host:port`；`system` 返回 null。非法配置抛 IllegalArgumentException。 */
    fun proxyUri(): String? {
        val m = ProxyMode.parse(mode)
        if (m == ProxyMode.SYSTEM) return null
        if (port < 1 || port > 65535) throw IllegalArgumentException("代理端口必须是 1～65535 的整数。")
        return "${m.wire}://${normalizedHost()}:$port"
    }

    /** 给 ProxyRelay 用的上游串（含认证）。`system` 返回 null。 */
    fun upstream(): String? {
        val uri = proxyUri() ?: return null
        if (username.isEmpty()) return uri
        val scheme = uri.substringBefore("://")
        val rest = uri.substringAfter("://")
        return "$scheme://${enc(username)}:${enc(password)}@$rest"
    }

    private fun enc(v: String) = java.net.URLEncoder.encode(v, "UTF-8").replace("+", "%20")

    private fun normalizedHost(): String {
        var h = host.trim()
        if (h.startsWith("[") && h.endsWith("]")) h = h.substring(1, h.length - 1)
        if (h.isEmpty() || h.length > 253) throw hostError()
        // 先当 IP 试；IPv6 要补回方括号。
        // 注意不能只做字符集匹配——那样 "1.2.3.4:8080"（其实是带端口的地址）会被当成 IPv6 放过。
        if (h.contains(':')) {
            if (!isIpv6Literal(h)) throw hostError()
            return "[$h]"
        }
        if (!HOST_RE.matches(h)) throw hostError()
        if (h.startsWith("-") || h.endsWith("-") || h.startsWith(".") || h.endsWith(".")) throw hostError()
        if (h.split('.').any { it.isEmpty() || it.length > 63 }) throw hostError()
        return h
    }

    private fun hostError() = IllegalArgumentException(
        "代理地址只填写 IP 或主机名，不要填写协议、端口、用户名或路径。")

    private fun isIpv6Literal(text: String): Boolean {
        if (text.count { it == ':' } < 2) return false          // 至少两个冒号，排除 host:port
        if (text.contains(":::")) return false
        val parts = text.split("::")
        if (parts.size > 2) return false
        val compressed = parts.size == 2
        val groups = parts.flatMap { seg ->
            if (seg.isEmpty()) emptyList() else seg.split(':')
        }
        if (groups.any { !it.matches(Regex("^[0-9A-Fa-f]{1,4}$")) }) return false
        return if (compressed) groups.size <= 7 else groups.size == 8
    }
}

/**
 * 落盘。对 `ProxySettingsStore`：
 * **读和写都先跑一遍校验**（ref: L46 / L49），坏配置绝不静默变成直连。
 */
class ProxySettingsStore(directory: File) {

    private val file = File(directory, "proxy-settings.json")
    // encodeDefaults 必须是 true。否则「跟随系统 + 127.0.0.1:0 + 空认证」这一整套默认值会被
    // kotlinx.serialization 全部省略，保存写出 `{}`，紧接着被下面的 mode 检查判成坏配置 ——
    // App 自己锁死自己，而且重新保存还是写 `{}`。写法与 TaskSettingsStore /
    // ArchiveStore / JobStateStore 对齐。
    private val json = Json { ignoreUnknownKeys = true; prettyPrint = true; encodeDefaults = true }

    fun load(): ProxySettings {
        if (!file.exists()) return ProxySettings()
        val text = file.readText(Charsets.UTF_8)
        // 按 JSON 结构判断 mode 字段在不在；text.contains 会被值里出现的 "mode" 骗过去。
        val obj = try {
            json.parseToJsonElement(text) as? JsonObject
        } catch (e: Exception) {
            throw java.io.IOException("代理配置无法读取，请在高级设置中重新保存。", e)
        } ?: throw java.io.IOException("代理配置无法读取，请在高级设置中重新保存。")
        if (!obj.containsKey("mode")) {
            // 自愈：encodeDefaults 修复（bug #1）之前的那版写「全默认值」会落盘成 `{}`，
            // 而 `{}` 又会被本方法拒收 —— App 自己锁死自己，重新保存还是写 `{}`。
            // 空对象恰好就是那版能写出来的全部内容，语义等价于 ProxySettings() 默认值
            // （跟随系统 + 127.0.0.1:0 + 空认证），所以按默认值迁移并立即改写回完整格式。
            // 只有「空对象」享受这条迁移：缺 mode 但带内容的文件仍然一律拒收，
            // 缺 mode 但带内容的老文件同样迁移：旧写入器只省略「等于默认值」的字段，所以缺
            // mode 恰好证明当年存的就是默认方式（跟随系统），保留其余字段后立即回写。
            // 真正无法判断意图的只有 JSON 都解析不了的文件，那种仍然一律拒收。
            val migrated = try {
                json.decodeFromString(ProxySettings.serializer(), text)
            } catch (e: Exception) {
                throw java.io.IOException("代理配置无法读取，请在高级设置中重新保存。", e)
            }
            save(migrated)
            return migrated
        }
        val value = try {
            json.decodeFromString(ProxySettings.serializer(), text)
        } catch (e: Exception) {
            throw java.io.IOException("代理配置无法读取，请在高级设置中重新保存。", e)
        }
        value.proxyUri()   // 校验；非法直接抛，不返回一个"能用"的对象
        return value
    }

    fun save(value: ProxySettings) {
        value.proxyUri()
        AtomicFiles.write(file, json.encodeToString(ProxySettings.serializer(), value))
    }

    companion object {
        /** ref: ProxySettings.cs:L54 —— 实例复制时连代理配置一起带走。 */
        fun copy(source: File, target: File) =
            ProxySettingsStore(target).save(ProxySettingsStore(source).load())
    }
}
