// ref: reference/Arena模型助手-源码-fyb-0.1.0/src/ProbeReader.cs
// spec: docs/mcp-android-implementation-plan.md §3.9
package ai.arena.companion.app

import ai.arena.companion.automation.ProbeReader
import ai.arena.companion.automation.ProbeSnapshot
import android.webkit.WebView
import kotlin.coroutines.resume
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import org.json.JSONObject

/**
 * 读取探针快照。
 *
 * **读不到一律返回带 `lastError` 的空快照，绝不抛**：探针是可选增强，
 * 注入失败时阶段机要能以「未识别（探针未加载）」正常收尾，而不是让整轮失败（§3.9 静默降级）。
 */
class WebViewProbeReader(
    private val webView: WebView,
    private val timeoutMillis: Long = 4000,
) : ProbeReader {

    override suspend fun read(): ProbeSnapshot {
        val raw = try {
            withTimeout(timeoutMillis) {
                withContext(Dispatchers.Main) {
                    suspendCancellableCoroutine<String?> { cont ->
                        webView.evaluateJavascript(SCRIPT) { cont.resume(it) }
                    }
                }
            }
        } catch (e: TimeoutCancellationException) {
            return ProbeSnapshot(lastError = "探针读取超时")
        } catch (e: Exception) {
            return ProbeSnapshot(lastError = e.message ?: "探针读取失败")
        }
        if (raw.isNullOrBlank() || raw == "null") {
            return ProbeSnapshot(lastError = "探针尚未加载")
        }
        return try {
            // evaluateJavascript 返回 JSON 字面量；这里外层是被 JSON.stringify 过的字符串。
            val text = JSONObject("{\"v\":$raw}").optString("v")
            val o = JSONObject(text)
            ProbeSnapshot(
                api = o.optBoolean("api"),
                runId = o.optString("runId").ifEmpty { null },
                name = o.optString("name").ifEmpty { null },
                lastError = o.optString("lastError").ifEmpty { null },
            )
        } catch (e: Exception) {
            ProbeSnapshot(lastError = "探针返回无法解析：${e.message}")
        }
    }

    private companion object {
        /** 一次取回整个探针状态；不拆成多次读取，避免 runId 与 name 来自不同时刻。 */
        const val SCRIPT =
            "JSON.stringify((window.__ARENA_MODEL_PROBE__&&__ARENA_MODEL_PROBE__.snapshot&&" +
                "__ARENA_MODEL_PROBE__.snapshot())||null)"
    }
}
